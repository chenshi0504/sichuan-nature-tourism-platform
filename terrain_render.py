# -*- coding: utf-8 -*-
"""四川地形底图渲染：把 Terrarium 高程瓦片渲染成「分层设色 + 山体晕渲」。

思路和轨道交通平台一致——瓦片全部由本地服务端代理并落盘缓存，浏览器只访问
127.0.0.1，境外网络抖动或离线复用都不影响看图。

数据源：AWS Open Data 的 Terrarium 高程瓦片
    https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
解码：elevation = (R * 256 + G + B / 256) - 32768（米）

对外：
    render(z, x, y, style) -> PNG bytes | None
    sample(lat, lon) -> 高程（米）
    profile(points) -> [(lat, lon, ele), ...]
"""
import io
import math
import os
import threading
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
DEM_DIR = os.path.join(BASE, "static", "tilecache", "dem")
OUT_DIR = os.path.join(BASE, "static", "tilecache", "render")
# 改配色 / 改算法时 +1，旧缓存自动失效
STYLE_VERSION = "v3"

DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEM_FALLBACK = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
DEM_UA = "SichuanTerrainAtlas/1.0 (local research tool)"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

MAX_NATIVE_Z = 13          # 再往上的缩放交给浏览器放大，避免无意义的高倍采样
NODATA = -1000.0

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path):
    with _LOCKS_GUARD:
        lk = _LOCKS.get(path)
        if lk is None:
            lk = _LOCKS[path] = threading.Lock()
        return lk


# ------------------------------------------------------------------ 瓦片读取
def dem_path(z, x, y):
    return os.path.join(DEM_DIR, str(z), str(x), "%d.png" % y)


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": DEM_UA})
    with OPENER.open(req, timeout=15) as resp:
        return resp.read()


def fetch_dem(z, x, y):
    """取高程瓦片（本地缓存优先）。z 超过 MAX_NATIVE_Z 时用父级瓦片顶上。"""
    if z > MAX_NATIVE_Z:
        shift = z - MAX_NATIVE_Z
        z, x, y = MAX_NATIVE_Z, x >> shift, y >> shift
    if not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    path = dem_path(z, x, y)
    if os.path.exists(path):
        return path
    lk = _lock_for(path)
    with lk:
        if os.path.exists(path):
            return path
        data = None
        for tpl in (DEM_URL, DEM_FALLBACK):
            try:
                data = _download(tpl.format(z=z, x=x, y=y))
                if data and len(data) > 60:
                    break
                data = None
            except Exception:  # noqa: BLE001
                data = None
        if not data:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        return path


# 解码结果在内存里留一份，剖面采样一条线会反复命中同几张瓦片
_TILE_CACHE = OrderedDict()
_TILE_CACHE_MAX = 96
_TILE_CACHE_LOCK = threading.Lock()


def _decode(path):
    with _TILE_CACHE_LOCK:
        if path in _TILE_CACHE:
            _TILE_CACHE.move_to_end(path)
            return _TILE_CACHE[path]
    try:
        with Image.open(path) as img:
            arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None
    if arr.shape[0] != 256 or arr.shape[1] != 256:
        return None
    ele = arr[..., 0] * 256.0 + arr[..., 1] + arr[..., 2] / 256.0 - 32768.0
    ele[ele < -900.0] = np.nan
    with _TILE_CACHE_LOCK:
        _TILE_CACHE[path] = ele
        while len(_TILE_CACHE) > _TILE_CACHE_MAX:
            _TILE_CACHE.popitem(last=False)
    return ele


def prefetch(points, z=12, workers=6):
    """并发预取一条路径涉及的高程瓦片，避免逐个串行下载拖慢剖面。"""
    tiles = set()
    for lat, lon in points:
        tiles.add(_lonlat_to_tile(lat, lon, z))
    todo = [t for t in tiles if not os.path.exists(dem_path(z, t[0], t[1]))]
    if not todo:
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda t: fetch_dem(z, t[0], t[1]), todo))


def dem_patch(z, x, y):
    """取 (z,x,y) 及其 8 邻域，拼成 770x770，中心 258x258 留作梯度计算缓冲。"""
    canvas = np.full((3 * 256, 3 * 256), np.nan, dtype=np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < 2 ** z and 0 <= ny < 2 ** z):
                continue
            path = fetch_dem(z, nx, ny)
            if not path:
                continue
            arr = _decode(path)
            if arr is None:
                continue
            canvas[(dy + 1) * 256:(dy + 1) * 256 + 256,
                   (dx + 1) * 256:(dx + 1) * 256 + 256] = arr
    core = canvas[256:513, 256:513]          # 257x257：中心瓦片 + 右/下各 1 像素
    if np.all(np.isnan(core)):
        return None
    return core


# ------------------------------------------------------------------ 高程色带
# 分层设色：平原淡水绿 → 丘陵黄绿 → 中山赭石 → 高山灰紫 → 雪线近白
RAMP = [
    (-50.0, (186, 218, 198)),
    (200.0, (182, 212, 176)),
    (600.0, (192, 214, 158)),
    (1100.0, (208, 212, 146)),
    (1700.0, (220, 206, 142)),
    (2300.0, (222, 194, 140)),
    (2900.0, (214, 178, 138)),
    (3500.0, (204, 164, 138)),
    (4100.0, (196, 156, 146)),
    (4700.0, (198, 170, 176)),
    (5300.0, (210, 190, 202)),
    (5900.0, (228, 216, 226)),
    (6500.0, (243, 240, 246)),
    (7400.0, (253, 253, 255)),
    (9000.0, (255, 255, 255)),
]


def _ramp_colors(ele):
    xs = np.array([p[0] for p in RAMP], dtype=np.float32)
    cols = np.array([p[1] for p in RAMP], dtype=np.float32)
    out = np.empty(ele.shape + (3,), dtype=np.float32)
    e = np.nan_to_num(ele, nan=-50.0)
    for c in range(3):
        out[..., c] = np.interp(e, xs, cols[:, c])
    return out


def _smooth(arr, passes=1):
    """3x3 均值模糊（可分离，用累加实现），压制 DEM 噪声，避免晕渲出现麻点。"""
    a = arr.copy()
    for _ in range(passes):
        for axis in (0, 1):
            pad = np.pad(a, [(1, 1) if i == axis else (0, 0) for i in range(2)], mode="edge")
            if axis == 0:
                a = (pad[:-2, :] + pad[1:-1, :] + pad[2:, :]) / 3.0
            else:
                a = (pad[:, :-2] + pad[:, 1:-1] + pad[:, 2:]) / 3.0
    return a


def _z_factor(z):
    """低缩放级别下地形起伏被摊平，需要更大的高程夸张系数才有山体感。"""
    if z <= 6:
        return 4.2
    if z == 7:
        return 3.2
    if z == 8:
        return 2.4
    if z == 9:
        return 1.9
    if z == 10:
        return 1.5
    if z == 11:
        return 1.2
    return 1.0


def _smooth_passes(z):
    """放大级别越高，DEM 高频噪声越显眼，需要多模糊几遍。"""
    if z <= 6:
        return 5
    if z <= 8:
        return 4
    if z <= 10:
        return 3
    return 2


def _illumination(ele, z, lat):
    """返回 0~1 的受光强度（Lambert），光源西北 45°。"""
    mpp = 156543.03392 * max(math.cos(math.radians(lat)), 0.05) / (2 ** z)
    # 纬度跨度造成东西向像素长度不同，用平均纬度算即可
    zf = _z_factor(z)
    smooth = _smooth(ele, passes=_smooth_passes(z))
    with np.errstate(invalid="ignore"):
        # 用 2 像素跨度做中心差分，进一步压噪
        d_col = (smooth[:, 2:] - smooth[:, :-2]) / (2.0 * mpp) * zf
        d_row = (smooth[2:, :] - smooth[:-2, :]) / (2.0 * mpp) * zf
        d_col = np.pad(d_col, ((0, 0), (1, 1)), mode="edge")   # 向东
        d_row = np.pad(d_row, ((1, 1), (0, 0)), mode="edge")   # 向南
    p = d_col
    q = -d_row                                            # 向北
    nx, ny, nz = -p, -q, np.ones_like(p)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)

    az = math.radians(315.0)
    alt = math.radians(45.0)
    lx = math.sin(az) * math.cos(alt)
    ly = math.cos(az) * math.cos(alt)
    lz = math.sin(alt)
    illum = (nx * lx + ny * ly + nz * lz) / norm
    return np.clip(illum, 0.0, 1.0)


def _band_edges(ele, step=500.0):
    """分层设色分带线（每个 step 米的界线），让山体层次更清楚。"""
    band = np.floor(np.nan_to_num(ele, nan=-50.0) / step)
    edge = np.zeros(band.shape, dtype=bool)
    edge[:-1, :] |= band[:-1, :] != band[1:, :]
    edge[:, :-1] |= band[:, :-1] != band[:, 1:]
    return edge


def render(z, x, y, style="hyps"):
    """渲染一张 256x256 底图瓦片，返回 PNG 字节。style: hyps | hillshade"""
    patch = dem_patch(z, x, y)
    if patch is None:
        return None
    ele = patch[:256, :256]
    lat = _tile_center_lat(z, y)
    illum = _illumination(patch, z, lat)[:256, :256]

    if style == "hillshade":
        base = np.repeat(np.full(ele.shape + (1,), 248.0, dtype=np.float32), 3, axis=2)
        base *= (0.50 + 0.72 * illum)[..., None]
    else:
        tint = _ramp_colors(ele)
        # 省域尺度上抬高山影的底色，避免整张图出现"揉皱的纸"那种密度
        if z <= 7:
            shade = 0.68 + 0.38 * illum
        elif z <= 9:
            shade = 0.58 + 0.52 * illum
        else:
            shade = 0.50 + 0.62 * illum
        if z >= 9:
            shade = np.where(_band_edges(ele), shade * 0.88, shade)
        base = tint * shade[..., None]
        # 背光面朝冷色偏一点，山体立体感和"阴坡/阳坡"更明显
        cool = np.clip((0.52 - illum) / 0.52, 0.0, 1.0) * 0.15
        base = base * (1.0 - cool[..., None]) + np.array([108.0, 122.0, 150.0]) * cool[..., None]

    rgb = np.clip(base, 0, 255).astype(np.uint8)
    alpha = np.where(np.isnan(ele), 0, 255).astype(np.uint8)
    if alpha.min() == 0:
        rgba = np.dstack([rgb, alpha])
        img = Image.fromarray(rgba, "RGBA")
    else:
        img = Image.fromarray(rgb, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _tile_center_lat(z, y):
    n = math.pi - 2.0 * math.pi * y / (2 ** z)
    return math.degrees(math.atan(math.sinh(n)))


# ------------------------------------------------------------------ 高程采样
def _lonlat_to_tile(lat, lon, z):
    lat = max(min(lat, 85.0), -85.0)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_pixel(lat, lon, z, x, y):
    n = 2 ** z
    fx = (lon + 180.0) / 360.0 * n - x
    lat_rad = math.radians(lat)
    fy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n - y
    px = int(np.clip(fx * 256, 0, 255))
    py = int(np.clip(fy * 256, 0, 255))
    return px, py


def sample(lat, lon, z=12):
    """单点高程（米），失败返回 None。"""
    x, y = _lonlat_to_tile(lat, lon, z)
    path = fetch_dem(z, x, y)
    if not path:
        return None
    arr = _decode(path)
    if arr is None:
        return None
    px, py = _tile_pixel(lat, lon, z, x, y)
    val = float(np.nanmean(arr[max(py - 1, 0):py + 2, max(px - 1, 0):px + 2]))
    if math.isnan(val) or val < -900:
        return None
    return round(val, 1)


def terrain_stats(lat, lon, radius_m=15000, z=11):
    """在点位 ±radius 的 3x3 网格上采样，估计周边起伏度，用于详情展示。"""
    step = max(radius_m, 1500.0)
    eles = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            dlat = di * step / 111320.0
            dlon = dj * step / (111320.0 * max(math.cos(math.radians(lat)), 0.2))
            v = sample(lat + dlat, lon + dlon, z=z)
            if v is not None:
                eles.append(v)
    if len(eles) < 3:
        return None
    return {
        "center": sample(lat, lon, z=z),
        "min": round(min(eles), 0),
        "max": round(max(eles), 0),
        "relief": round(max(eles) - min(eles), 0),
        "radius_km": round(radius_m / 1000.0, 1),
    }


def profile(points, z=12):
    """沿路径等距采样高程，返回剖面点。points: [(lat, lon), ...]"""
    if len(points) < 2:
        return []
    out = []
    # 用球面距离把相邻点的连线切成约 500m 一段
    total = 0.0
    seg = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        dx = (b[1] - a[1]) * 111320.0 * math.cos(math.radians((a[0] + b[0]) / 2))
        dy = (b[0] - a[0]) * 111320.0
        d = math.hypot(dx, dy)
        seg.append(d)
        total += d
    if total <= 0:
        return out
    n = int(min(max(total / 1200.0, 24), 180))
    for k in range(n + 1):
        target = total * k / n
        acc = 0.0
        for i, d in enumerate(seg):
            if acc + d >= target or i == len(seg) - 1:
                t = 0.0 if d <= 0 else (target - acc) / d
                t = min(max(t, 0.0), 1.0)
                lat = points[i][0] + (points[i + 1][0] - points[i][0]) * t
                lon = points[i][1] + (points[i + 1][1] - points[i][1]) * t
                out.append((lat, lon))
                break
            acc += d
    prefetch(out, z=z)
    res = []
    dist = 0.0
    prev = None
    for lat, lon in out:
        if prev:
            dx = (lon - prev[1]) * 111320.0 * math.cos(math.radians(lat))
            dy = (lat - prev[0]) * 111320.0
            dist += math.hypot(dx, dy)
        prev = (lat, lon)
        ele = sample(lat, lon, z=z)
        res.append({"lat": round(lat, 5), "lon": round(lon, 5),
                    "dist_km": round(dist / 1000.0, 2),
                    "ele": ele})
    return res


def cached_render(z, x, y, style="hyps"):
    """带磁盘缓存的渲染入口。"""
    path = os.path.join(OUT_DIR, STYLE_VERSION, style, str(z), str(x), "%d.png" % y)
    if os.path.exists(path):
        return path
    data = render(z, x, y, style)
    if data is None:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return path

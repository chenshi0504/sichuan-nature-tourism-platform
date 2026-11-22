# -*- coding: utf-8 -*-
"""把 data/raw 下的 Overpass 原始结果整理成平台直接可用的数据文件：

  data/terrain_labels.json   地形注记（山峰 / 山脊 / 湖泊 / 冰川 / 草原 / 保护地）
  data/rivers.geojson        主要河流几何（简化后）
  data/osm_index.json        名称 -> OSM 坐标，用于校核人工整理的资源点
  data/elevation_cache.json  每个资源点由 DEM 采样的高程

同时打印「人工坐标 vs OSM 坐标」的距离清单，超过阈值的需要人工复核。
"""
import json
import math
import os
import re
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

RAW = os.path.join(BASE, "data", "raw")
DATA = os.path.join(BASE, "data")

BBOX = (25.7, 97.0, 34.6, 108.9)   # south, west, north, east

# OSM 里常以藏语/英语登记，这些名字优先用中文标签
NAME_ZH = ("name:zh", "name:zh-Hans", "name:zh_pinyin", "name")

FAMOUS = {
    "贡嘎山", "四姑娘山", "峨眉山", "青城山", "雪宝顶", "雀儿山", "格聂神山",
    "仙乃日", "央迈勇", "夏诺多吉", "幺妹峰", "西岭雪山", "九顶山", "折多山",
    "巴郎山", "二郎山", "卡子拉山", "剪子弯山", "海子山", "牛背山", "达瓦更扎",
    "泸沽湖", "邛海", "马湖", "木格措", "新路海", "卡萨湖", "伍须海", "叠溪海子",
}


def parse_ele(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("m", "").replace("米", "").strip())
    except ValueError:
        return None


def in_bbox(lat, lon):
    return BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]


def load_elements(prefix):
    out = []
    for name in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
        if not (name.startswith(prefix) and name.endswith(".json")):
            continue
        path = os.path.join(RAW, name)
        if os.path.getsize(path) < 100:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except ValueError:
            continue
        out.extend(payload.get("elements", []))
    return out


def element_point(el):
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    center = el.get("center") or {}
    if "lat" in center and "lon" in center:
        return center["lat"], center["lon"]
    return None


def display_name(tags):
    for key in NAME_ZH:
        val = (tags.get(key) or "").strip()
        if val:
            return val
    return ""


def classify(tags):
    if tags.get("natural") == "peak":
        return "peak"
    if tags.get("natural") == "ridge":
        return "ridge"
    if tags.get("natural") == "glacier":
        return "glacier"
    if tags.get("natural") == "grassland":
        return "grassland"
    if tags.get("natural") == "water" or tags.get("water") in ("lake", "reservoir"):
        return "lake"
    if tags.get("boundary") == "protected_area" or tags.get("leisure") == "nature_reserve":
        return "park"
    return None


def min_zoom_for(kind, ele, is_relation):
    if kind == "peak":
        if ele is None:
            return 10.8
        if ele >= 6800:
            return 5.0
        if ele >= 6000:
            return 6.0
        if ele >= 5500:
            return 7.2
        if ele >= 5000:
            return 8.0
        if ele >= 4600:
            return 8.6
        if ele >= 4200:
            return 9.2
        if ele >= 3800:
            return 9.8
        return 10.8
    if kind == "ridge":
        return 8.4
    if kind == "glacier":
        return 8.4
    if kind == "grassland":
        return 9.0
    if kind == "lake":
        return 8.0 if is_relation else 9.6
    return 8.4


def river_labels(river_feats):
    """沿主要河流取样打点，生成河名注记（每条 1–2 处）。"""
    out = []
    for feat in river_feats or []:
        lines = (feat.get("geometry") or {}).get("coordinates") or []
        if not lines:
            continue
        longest = max(lines, key=len)
        if len(longest) < 4:
            continue
        picks = [0.45] if len(longest) < 60 else [0.3, 0.7]
        for frac in picks:
            x, y = longest[min(int(len(longest) * frac), len(longest) - 1)]
            out.append({"name": feat["properties"]["name"], "kind": "river",
                        "lat": round(y, 5), "lon": round(x, 5), "ele": None, "minZoom": 6.5})
    return out


def build_labels(river_feats=None):
    elements = load_elements("features_")
    best = {}
    for el in elements:
        tags = el.get("tags") or {}
        kind = classify(tags)
        if not kind:
            continue
        pt = element_point(el)
        if not pt or not in_bbox(*pt):
            continue
        name = display_name(tags)
        if not name or len(name) > 24:
            continue
        # 纯拉丁字母的名字在中文地形图上只会添乱（OSM 里不少湖只有英文名）
        if not any("\u4e00" <= ch <= "\u9fff" for ch in name):
            continue
        ele = parse_ele(tags.get("ele"))
        if kind == "peak" and ele is None:
            # 无高程的山峰只保留知名名单里的，否则注记会过密
            if name not in FAMOUS:
                continue
        if kind == "peak" and ele is not None and ele < 3400 and name not in FAMOUS:
            continue
        key = (name, kind)
        score = (ele or 0) + (2 if el["type"] == "relation" else 0)
        prev = best.get(key)
        if prev is None or score > prev["score"]:
            best[key] = {
                "name": name, "kind": kind, "lat": round(pt[0], 5), "lon": round(pt[1], 5),
                "ele": ele,
                "minZoom": min_zoom_for(kind, ele, el["type"] == "relation"),
                "score": score,
            }
    labels = list(best.values()) + river_labels(river_feats)
    labels.sort(key=lambda x: (x["kind"], x["minZoom"], -(x["ele"] or 0)))
    for item in labels:
        item.pop("score", None)
    with open(os.path.join(DATA, "terrain_labels.json"), "w", encoding="utf-8") as fh:
        json.dump(labels, fh, ensure_ascii=False, indent=1)
    kinds = defaultdict(int)
    for item in labels:
        kinds[item["kind"]] += 1
    print("[labels]", len(labels), dict(kinds))
    return labels


def rdp(points, eps=0.0012):
    """Douglas-Peucker 简化，坐标单位为度。"""
    if len(points) < 3:
        return points
    stack = [(0, len(points) - 1)]
    keep = {0, len(points) - 1}
    while stack:
        start, end = stack.pop()
        ax, ay = points[start]
        bx, by = points[end]
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        best_i, best_d = -1, 0.0
        for i in range(start + 1, end):
            px, py = points[i]
            if denom <= 1e-12:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best_d:
                best_i, best_d = i, d
        if best_d > eps and best_i > 0:
            keep.add(best_i)
            stack.append((start, best_i))
            stack.append((best_i, end))
    return [points[i] for i in sorted(keep)]


# Natural Earth 1:10M 河流的英文名 -> 中文名（只在 OSM 缺失时兜底）
NE_NAMES = {
    "Jinsha": "金沙江", "Chang Jiang": "长江", "Dadu": "大渡河", "Min": "岷江",
    "Yalong": "雅砻江", "Jialing": "嘉陵江", "Tuo": "沱江", "Huang": "黄河",
    "Lancang": "澜沧江",
}

# 繁简 / 别名归并
NAME_ALIAS = {
    "雅礱江": "雅砻江", "雅砻江上游": "雅砻江", "金砂江": "金沙江",
    "大渡河干流": "大渡河", "岷江干流": "岷江",
}


def build_rivers():
    """优先用 OSM 的河道几何；缺失的大河用 Natural Earth 概化线补齐。"""
    elements = load_elements("rivers_") + load_elements("river_")
    by_name = defaultdict(list)
    for el in elements:
        tags = el.get("tags") or {}
        name = NAME_ALIAS.get(display_name(tags), display_name(tags))
        geom = el.get("geometry") or []
        if not name or len(geom) < 2:
            continue
        pts = [(round(g["lon"], 4), round(g["lat"], 4)) for g in geom if "lon" in g]
        if len(pts) < 2:
            continue
        if not any(in_bbox(lat, lon) for lon, lat in pts):
            continue
        by_name[name].append(rdp(pts))

    osm_names = set(by_name)
    ne_path = os.path.join(DATA, "ne_rivers.geojson")
    if os.path.exists(ne_path):
        with open(ne_path, encoding="utf-8") as fh:
            ne = json.load(fh)
        pad = 0.6
        for feat in ne.get("features", []):
            props = feat.get("properties") or {}
            zh = NE_NAMES.get((props.get("name") or "").strip())
            if not zh or zh in osm_names:
                continue
            geom = feat.get("geometry") or {}
            lines = [geom["coordinates"]] if geom.get("type") == "LineString" \
                else (geom.get("coordinates") or [])
            for line in lines:
                pts = [(round(x, 4), round(y, 4)) for x, y in line
                       if BBOX[1] - pad <= x <= BBOX[3] + pad
                       and BBOX[0] - pad <= y <= BBOX[2] + pad]
                if len(pts) >= 2:
                    by_name[zh].append(rdp(pts, 0.006))

    feats = []
    total = 0
    for name, lines in by_name.items():
        lines.sort(key=len, reverse=True)
        # 同一句河名被切成很多 way，保留足够长的主干段，避免碎线太多
        kept = [ln for ln in lines if len(ln) >= 3][:40] or lines[:5]
        total += len(kept)
        feats.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "segments": len(kept),
                "source": "osm" if name in osm_names else "ne",
            },
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[x, y] for x, y in ln] for ln in kept]},
        })
    with open(os.path.join(DATA, "rivers.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)
    src = defaultdict(int)
    for f in feats:
        src[f["properties"]["source"]] += 1
    print("[rivers]", len(feats), "names,", total, "segments", dict(src))
    return feats


def build_boundary():
    path = os.path.join(RAW, "boundary.json")
    if not os.path.exists(path):
        print("[boundary] raw missing, skipped")
        return
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    lines = []
    for el in payload.get("elements", []):
        for member in el.get("members", []):
            if member.get("type") != "way":
                continue
            pts = [(round(g["lon"], 4), round(g["lat"], 4))
                   for g in (member.get("geometry") or []) if "lon" in g]
            if len(pts) >= 2:
                lines.append(rdp(pts, 0.004))
    out = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": "四川省"},
        "geometry": {"type": "MultiLineString", "coordinates": lines},
    }]}
    with open(os.path.join(DATA, "boundary.geojson"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("[boundary]", len(lines), "segments")


def build_index():
    """名称 -> OSM 坐标，用于校核 resources.json 里人工写的坐标。"""
    index = defaultdict(list)
    for el in load_elements("features_"):
        tags = el.get("tags") or {}
        name = display_name(tags)
        pt = element_point(el)
        if not name or not pt:
            continue
        index[name].append({"lat": pt[0], "lon": pt[1],
                            "kind": classify(tags) or "other",
                            "ele": parse_ele(tags.get("ele"))})
    with open(os.path.join(DATA, "osm_index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False)
    print("[index]", len(index), "names")
    return index


def dist_km(a, b):
    dl = (a[0] - b[0]) * 111.32
    dn = (a[1] - b[1]) * 111.32 * max(math.cos(math.radians(a[0])), 0.2)
    return math.hypot(dl, dn)


def build_elevations(index):
    import terrain_render
    with open(os.path.join(DATA, "resources.json"), encoding="utf-8") as fh:
        resources = json.load(fh)
    cache = {}
    path = os.path.join(DATA, "elevation_cache.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except ValueError:
            cache = {}
    missing = [r for r in resources if r["id"] not in cache]
    print("[elev] sampling", len(missing), "of", len(resources))
    for item in missing:
        ele = terrain_render.sample(item["lat"], item["lon"])
        if ele is not None:
            cache[item["id"]] = ele
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    print("[elev] cached", len(cache))
    return cache


def build_terrain_stats():
    """预计算每个资源点 ±12km 的地形起伏，详情卡直接读缓存，避免每次现算。"""
    import terrain_render
    with open(os.path.join(DATA, "resources.json"), encoding="utf-8") as fh:
        resources = json.load(fh)
    path = os.path.join(DATA, "terrain_stats.json")
    cache = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except ValueError:
            cache = {}
    todo = [r for r in resources if r["id"] not in cache]
    print("[terrain] computing", len(todo), "of", len(resources))
    for item in todo:
        stats = terrain_render.terrain_stats(item["lat"], item["lon"], radius_m=12000)
        if stats:
            cache[item["id"]] = stats
            print("  %-14s %s" % (item["name"], stats), flush=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    print("[terrain] cached", len(cache))


def check_elevation():
    """用 DEM 采样值反查坐标是否落在正确的位置上。

    资源 tags 里写了「4040m」「2690m」这类自身海拔的，直接和 DEM 比对；
    偏差过大说明坐标不在实景位置上，需要人工核对。
    """
    with open(os.path.join(DATA, "resources.json"), encoding="utf-8") as fh:
        resources = json.load(fh)
    try:
        with open(os.path.join(DATA, "elevation_cache.json"), encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        return
    print("\n高程自检（|DEM - 标称| > 700 m 的需要复核）")
    bad = 0
    for item in resources:
        dem = cache.get(item["id"])
        if dem is None:
            continue
        claims = []
        if item.get("ele"):
            claims.append(float(item["ele"]))
        for tag in item.get("tags") or []:
            m = re.match(r"^(\d{3,4})\s*m$", tag.strip(), re.I)
            if m:
                claims.append(float(m.group(1)))
        if not claims:
            continue
        claim = max(claims)
        if abs(dem - claim) > 700:
            bad += 1
            print("  !! %-14s DEM %5.0f  标称 %5.0f  (%.3f,%.3f)"
                  % (item["name"], dem, claim, item["lat"], item["lon"]))
    print("  待复核", bad, "条（共", len([r for r in resources if cache.get(r["id"]) is not None]), "条已采样）")


def check_coords(index):
    with open(os.path.join(DATA, "resources.json"), encoding="utf-8") as fh:
        resources = json.load(fh)
    print("\n%-18s %-8s %-9s %s" % ("name", "dist_km", "osm_kind", "备注"))
    worst = []
    for item in resources:
        cands = index.get(item["name"]) or []
        if not cands:
            worst.append((None, item["name"], "", "OSM 无同名要素"))
            continue
        best = min(cands, key=lambda c: dist_km((item["lat"], item["lon"]), (c["lat"], c["lon"])))
        d = dist_km((item["lat"], item["lon"]), (best["lat"], best["lon"]))
        if d > 4.0:
            worst.append((d, item["name"], best["kind"],
                          "%.4f,%.4f -> %.4f,%.4f" % (item["lat"], item["lon"], best["lat"], best["lon"])))
    worst.sort(key=lambda x: -(x[0] or 0))
    for d, name, kind, note in worst:
        flag = "!!" if (d or 0) > 12 else "  "
        print("%s %-18s %-8s %-9s %s" % (flag, name, "—" if d is None else round(d, 1), kind, note))
    print("待复核", len(worst), "条")


def main():
    rivers = build_rivers()
    build_labels(rivers)
    build_boundary()
    index = build_index()
    check_coords(index)
    if "--no-elev" not in sys.argv:
        build_elevations(index)
        build_terrain_stats()
        check_elevation()


if __name__ == "__main__":
    main()

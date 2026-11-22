# -*- coding: utf-8 -*-
"""抓取四川省域内的 OSM 地形要素，落盘到 data/raw/。

两类数据分开抓，避免单次查询超时：
  1) features  ：山峰 / 山脊 / 湖泊 / 冰川 / 草原 / 保护区（只要中心点 + 标签）
  2) rivers    ：主要河流的真实几何（out geom），用于地图上的蓝色水系线

用法：
    python -X utf8 tools/fetch_osm.py            # 全部
    python -X utf8 tools/fetch_osm.py features   # 只抓要素
    python -X utf8 tools/fetch_osm.py rivers     # 只抓河流
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")

# 四川省域外扩一点，保证边界上的山系、河流不被截断
SOUTH, WEST, NORTH, EAST = 25.85, 97.15, 34.45, 108.75
# 东西向 11.6°、南北向 8.6°，切成 4x3 块逐个抓，单块响应可控
NX, NY = 4, 3

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# 山脊/湖泊/草原/保护区只保留带名字的；山峰是地形注记的主角，全部保留
FEATURE_QUERY = """
[out:json][timeout:180];
(
  node["natural"="peak"]["name"]({bbox});
  way["natural"="ridge"]["name"]({bbox});
  relation["natural"="ridge"]["name"]({bbox});
  way["natural"="water"]["name"]({bbox});
  relation["natural"="water"]["name"]({bbox});
  way["water"="reservoir"]["name"]({bbox});
  relation["water"="reservoir"]["name"]({bbox});
  way["natural"="glacier"]["name"]({bbox});
  way["natural"="grassland"]["name"]({bbox});
  relation["natural"="grassland"]["name"]({bbox});
  way["boundary"="protected_area"]["name"]({bbox});
  relation["boundary"="protected_area"]["name"]({bbox});
  relation["leisure"="nature_reserve"]["name"]({bbox});
);
out center tags;
"""

MAJOR_RIVERS = [
    "长江", "金沙江", "雅砻江", "大渡河", "岷江", "青衣江", "嘉陵江",
    "涪江", "渠江", "沱江", "安宁河", "白龙江", "理塘河", "鲜水河",
    "黄河", "小金川", "梭磨河", "黑水河", "美姑河", "越西河",
]

RIVER_QUERY = """
[out:json][timeout:300];
way["waterway"="river"]["name"~"^({names})$"]({bbox});
out geom;
"""


def bboxes(nx=NX, ny=NY):
    dlon = (EAST - WEST) / nx
    dlat = (NORTH - SOUTH) / ny
    out = []
    for i in range(nx):
        for j in range(ny):
            s = SOUTH + j * dlat
            w = WEST + i * dlon
            out.append((s, w, s + dlat, w + dlon))
    return out


def fetch(query, attempts=2):
    last = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(attempts):
        for endpoint in ENDPOINTS:
            t0 = time.time()
            try:
                data = urllib.parse.urlencode({"data": query}).encode("utf-8")
                req = urllib.request.Request(
                    endpoint,
                    data=data,
                    headers={
                        "User-Agent": "SichuanTerrainAtlas/1.0 (local research tool)",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                with opener.open(req, timeout=150) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                print("    ok %.1fs %s (%d)" % (time.time() - t0, endpoint.split("/")[2],
                                                len(payload.get("elements", []))), flush=True)
                return payload
            except Exception as exc:  # noqa: BLE001
                last = exc
                print("    fail %s %s" % (endpoint.split("/")[2], repr(exc)[:120]), flush=True)
                time.sleep(2)
    raise SystemExit("all endpoints failed: %r" % (last,))


def save(name, payload):
    path = os.path.join(RAW, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    print("  ->", name, len(payload.get("elements", [])), "elements", flush=True)


def fetch_block(name, box, depth=0):
    """单块抓取；超时/504 时四等分重试，直到 0.35° 见方。"""
    s, w, n, e = box
    path = os.path.join(RAW, name)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        print("[%s] cached" % name, flush=True)
        return
    bbox = "%.3f,%.3f,%.3f,%.3f" % (s, w, n, e)
    print("[%s] %s %s" % (name, bbox, "(split%d)" % depth if depth else ""), flush=True)
    try:
        save(name, fetch(FEATURE_QUERY.format(bbox=bbox), attempts=1))
        return
    except SystemExit as exc:
        print("[%s] failed: %s" % (name, repr(exc)[:90]), flush=True)
    if depth >= 3 or min(n - s, e - w) < 0.8:
        print("[%s] give up" % name, flush=True)
        return
    ms, mw = (s + n) / 2.0, (w + e) / 2.0
    stem = name.replace(".json", "")
    quads = [
        ("a", (s, w, ms, mw)), ("b", (s, mw, ms, e)),
        ("c", (ms, w, n, mw)), ("d", (ms, mw, n, e)),
    ]
    for suffix, sub in quads:
        fetch_block("%s%s.json" % (stem, suffix), sub, depth + 1)


def run_features():
    for idx, box in enumerate(bboxes()):
        fetch_block("features_%02d.json" % idx, box)


def fetch_river_block(name, box, depth=0):
    s, w, n, e = box
    path = os.path.join(RAW, name)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        print("[%s] cached" % name, flush=True)
        return
    bbox = "%.3f,%.3f,%.3f,%.3f" % (s, w, n, e)
    print("[%s] %s" % (name, bbox), flush=True)
    try:
        save(name, fetch(RIVER_QUERY.format(names="|".join(MAJOR_RIVERS), bbox=bbox), attempts=1))
        return
    except SystemExit as exc:
        print("[%s] failed: %s" % (name, repr(exc)[:90]), flush=True)
    if depth >= 2:
        return
    mid = (s + n) / 2.0
    stem = name.replace(".json", "")
    for suffix, sub in (("s", (s, w, mid, e)), ("n", (mid, w, n, e))):
        fetch_river_block("%s%s.json" % (stem, suffix), sub, depth + 1)


def run_rivers():
    # 河流按南北三条横带抓，减少单次返回量
    step = (NORTH - SOUTH) / 3
    for idx, name in enumerate(["rivers_south.json", "rivers_mid.json", "rivers_north.json"]):
        s = SOUTH + idx * step
        fetch_river_block(name, (s, WEST, s + step, EAST))


def main():
    os.makedirs(RAW, exist_ok=True)
    want = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if want in ("all", "features"):
        run_features()
    if want in ("all", "rivers"):
        run_rivers()
    print("done", flush=True)


if __name__ == "__main__":
    main()

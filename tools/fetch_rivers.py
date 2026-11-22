# -*- coding: utf-8 -*-
"""按「一条河一个 bbox」的方式抓主要河流几何。

整省 or 大横带的 `out geom` 查询在 Overpass 上经常 504，拆成单条河流的小范围查询
才稳定。每个结果单独落盘，中断后重跑会跳过已完成的部分。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")

# 河流名 -> 覆盖其河道（含出省段）的 bbox：south, west, north, east
RIVERS = [
    ("金沙江", (25.5, 98.5, 31.5, 103.6)),
    ("长江", (28.0, 104.4, 31.0, 108.7)),
    ("雅砻江", (25.8, 99.0, 33.2, 102.6)),
    ("大渡河", (28.5, 101.0, 33.6, 104.2)),
    ("岷江", (28.5, 102.4, 33.6, 104.6)),
    ("嘉陵江", (29.5, 104.4, 33.6, 107.6)),
    ("涪江", (30.0, 103.5, 33.0, 106.6)),
    ("渠江", (30.0, 106.0, 32.6, 108.6)),
    ("沱江", (28.5, 103.9, 31.6, 105.6)),
    ("安宁河", (26.4, 101.4, 29.2, 102.9)),
    ("白龙江", (32.4, 103.4, 34.5, 106.0)),
    ("理塘河", (28.0, 99.9, 30.6, 101.6)),
    ("鲜水河", (30.0, 100.4, 32.6, 102.1)),
    ("青衣江", (29.0, 102.2, 31.1, 103.6)),
    ("小金川", (30.4, 101.9, 32.1, 103.1)),
    ("黄河", (32.4, 100.9, 34.6, 103.6)),
]

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
QUERY = """
[out:json][timeout:90];
way["waterway"="river"]["name"="{name}"]({bbox});
out geom;
"""


def fetch(query):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = None
    for endpoint in ENDPOINTS:
        try:
            data = urllib.parse.urlencode({"data": query}).encode("utf-8")
            req = urllib.request.Request(
                endpoint, data=data,
                headers={"User-Agent": "SichuanTerrainAtlas/1.0",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with opener.open(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            print("    fail %s %s" % (endpoint.split("/")[2], repr(exc)[:100]), flush=True)
            time.sleep(3)
    print("    give up: %r" % (last,), flush=True)
    return None


def main():
    os.makedirs(RAW, exist_ok=True)
    for idx, (name, box) in enumerate(RIVERS, 1):
        path = os.path.join(RAW, "river_%02d.json" % idx)
        if os.path.exists(path) and os.path.getsize(path) > 120:
            print("[%d/%d] %s cached" % (idx, len(RIVERS), name), flush=True)
            continue
        bbox = "%.2f,%.2f,%.2f,%.2f" % box
        print("[%d/%d] %s %s" % (idx, len(RIVERS), name, bbox), flush=True)
        payload = fetch(QUERY.format(name=name, bbox=bbox))
        if payload is None:
            continue
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        print("    -> %d ways" % len(payload.get("elements", [])), flush=True)
        time.sleep(4)
    print("done", flush=True)


if __name__ == "__main__":
    main()

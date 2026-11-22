# -*- coding: utf-8 -*-
"""抓取四川省行政边界（admin_level=4），用于地图上勾出省域轮廓。"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "raw", "boundary.json")
QUERY = """
[out:json][timeout:180];
relation["name"="四川省"]["admin_level"="4"];
out geom;
"""
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for endpoint in ENDPOINTS:
        try:
            data = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
            req = urllib.request.Request(
                endpoint, data=data,
                headers={"User-Agent": "SichuanTerrainAtlas/1.0",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with opener.open(req, timeout=240) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            members = sum(len(e.get("members", [])) for e in payload.get("elements", []))
            print("boundary ok:", endpoint, "members", members)
            return
        except Exception as exc:  # noqa: BLE001
            print("fail", endpoint, repr(exc)[:140])
    raise SystemExit("boundary fetch failed")


if __name__ == "__main__":
    main()

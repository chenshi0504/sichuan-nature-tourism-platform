# -*- coding: utf-8 -*-
"""用 OSM 同名要素 / 河流几何 / DEM 校核结果修正批次景点的坐标。

每条的校核依据写在注释里，便于追溯。
"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# id: (lat, lon, 依据)
FIXES = {
    "zhaogongshan": (30.9766, 103.5166),      # OSM 赵公山 peak ele=2434
    "yunding-shcheng": (30.7414, 104.4837),   # OSM 云顶山 peak，DEM 959m 台面
    "danjingshan": (31.0958, 103.8239),       # OSM 丹景山 peak，DEM 1132m
    "longquanshan": (30.550, 104.300),        # 龙泉山主脊，DEM 791m
    "danjingtai": (30.450, 104.302),          # 龙泉山南段山脊（三岔湖西北），DEM 660m
    "shixianghu": (30.197, 103.4240),         # OSM 石象湖 lake
    "micangshan": (32.6908, 106.9462),        # OSM 米仓山国家森林公园
    "bataishan": (32.1000, 108.1850),         # DEM 八台山脊，2372m 邻峰
    "ertan": (26.8210, 101.7810),             # 雅砻江几何点，库水位 1195m
    "yele": (28.7400, 102.3000),              # 冶勒乡，DEM 2704m
    "yalashan": (30.3808, 101.6998),          # OSM 雅拉雪山 peak ele=5820
    "jiajinshan": (30.8645, 102.6866),        # OSM 夹金山 peak ele=4260
    "wanggangping": (29.4790, 102.2840),      # OSM 王岗坪旅游景区
    "caoyutan": (29.8750, 103.1980),          # 青衣江几何点，河面 512m
    "huashuiwan": (30.6600, 103.2400),        # 西岭雪山东麓，DEM 1184m
    "longchi": (31.1050, 103.5850),           # 龙池湖，DEM 1818m
    "bowangshan": (28.3060, 104.9440),        # DEM 僰王山台地，1235m
}


def main():
    for path in ("_batch2.json", "resources.json"):
        full = os.path.join(DATA, path)
        rows = json.load(open(full, encoding="utf-8"))
        hit = 0
        for r in rows:
            fix = FIXES.get(r["id"])
            if fix:
                r["lat"], r["lon"] = fix
                hit += 1
        json.dump(rows, open(full, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(path, "updated", hit)

    ele_path = os.path.join(DATA, "elevation_cache.json")
    ele = json.load(open(ele_path, encoding="utf-8"))
    for rid in FIXES:
        ele.pop(rid, None)
    json.dump(ele, open(ele_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    st_path = os.path.join(DATA, "terrain_stats.json")
    st = json.load(open(st_path, encoding="utf-8"))
    for rid in FIXES:
        st.pop(rid, None)
    json.dump(st, open(st_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    conn = sqlite3.connect(os.path.join(BASE, "sichuan_terrain.db"))
    cur = conn.cursor()
    for rid, (lat, lon) in FIXES.items():
        cur.execute("UPDATE resources SET lat=?, lon=? WHERE id=?", (lat, lon, rid))
    conn.commit()
    print("db rows updated", conn.total_changes)
    conn.close()


if __name__ == "__main__":
    main()

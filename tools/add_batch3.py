# -*- coding: utf-8 -*-
"""补一批成都近郊自然景点（坐标经 OSM / DEM 校核），并修正丹景台措辞。"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

ITEMS = [
    {"id": "zipingpu", "name": "紫坪铺水库", "cat": "water", "city": "成都市",
     "level": "", "lon": 103.477, "lat": 31.098,
     "tags": ["岷江出山口", "156m 坝高", "回水至映秀"],
     "intro": "岷江刚冲出龙门山就被 156 米高的面板堆石坝拦住，回水一直上溯到映秀，"
              "是成都平原头顶最大的一盆水，也是都江堰灌区的调蓄库。"},
    {"id": "longquanhu", "name": "龙泉湖", "cat": "water", "city": "成都市",
     "level": "", "lon": 104.391, "lat": 30.511,
     "tags": ["石盘水库", "龙泉山东麓"],
     "intro": "龙泉山东坡的石盘水库，水面被丘陵切成几十个湾，湖岸是川中丘陵的紫红色砂泥岩台地。"},
    {"id": "jiufengshan", "name": "九峰山", "cat": "scenic", "city": "成都市",
     "level": "", "lon": 103.718, "lat": 31.272, "ele": 3292,
     "tags": ["龙门山北段", "3300m", "峰群"],
     "intro": "白水河上游的一组尖峰，九座山头并列排在龙门山推覆体上，海拔从 1500 米直上 3300 米。"},
    {"id": "wuzhongshan", "name": "雾中山", "cat": "scenic", "city": "成都市",
     "level": "", "lon": 103.285, "lat": 30.605,
     "tags": ["低山", "佛教名山", "1100–1400m"],
     "intro": "大邑东部的红层低山，主脊在 1100–1400 米之间，山间常年起雾，也是邛崃山脉向东伸进平原的最后一级台阶。"},
    {"id": "tuojiang-xiaosanxia", "name": "沱江小三峡", "cat": "gorge", "city": "成都市",
     "level": "", "lon": 104.450, "lat": 30.800,
     "tags": ["沱江", "金堂", "红层峡谷"],
     "intro": "沱江在金堂切穿龙泉山余脉形成的三段短峡——鳖灵峡、明月峡、九龙峡，"
              "谷壁是水平层理的白垩系红层，河面只有 440 米。"},
]


def main():
    path = os.path.join(DATA, "resources.json")
    rows = json.load(open(path, encoding="utf-8"))

    for r in rows:
        if r["id"] == "danjingtai":
            r["intro"] = ("龙泉山南段的山脊平台，天气好时向西可一眼看到贡嘎、"
                          "大雪塘与四姑娘山三组雪线。")

    ids = {r["id"] for r in rows}
    names = {r["name"] for r in rows}
    added = [i for i in ITEMS if i["id"] not in ids and i["name"] not in names]
    rows.extend(added)
    json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("added", len(added), "total", len(rows))

    conn = sqlite3.connect(os.path.join(BASE, "sichuan_terrain.db"))
    cur = conn.cursor()
    cur.execute("UPDATE resources SET intro=? WHERE id='danjingtai'",
                (next(r["intro"] for r in rows if r["id"] == "danjingtai"),))
    for item in added:
        cur.execute(
            "INSERT OR IGNORE INTO resources "
            "(id,name,cat,city,level,lon,lat,ele,dem_ele,tags,intro) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item["name"], item["cat"], item["city"], item["level"],
             item["lon"], item["lat"], item.get("ele"), None,
             "、".join(item["tags"]), item["intro"]),
        )
    conn.commit()
    print("db total", cur.execute("SELECT COUNT(*) FROM resources").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

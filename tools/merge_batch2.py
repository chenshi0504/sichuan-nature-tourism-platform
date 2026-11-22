# -*- coding: utf-8 -*-
"""把 data/_batch2.json 合并进 data/resources.json，并补进 sqlite。

去重规则：id 或 name 已存在的记录跳过。
"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def fix_quotes(text):
    return text.replace('最"湿"的峡谷', "最“湿”的峡谷").replace('天然"盆"', "天然“盆”")


def main():
    batch_path = os.path.join(DATA, "_batch2.json")
    raw = open(batch_path, encoding="utf-8").read()
    batch = json.loads(fix_quotes(raw))

    res_path = os.path.join(DATA, "resources.json")
    rows = json.load(open(res_path, encoding="utf-8"))

    ids = {r["id"] for r in rows}
    names = {r["name"] for r in rows}
    added = []
    for item in batch:
        if item["id"] in ids or item["name"] in names:
            continue
        rows.append(item)
        ids.add(item["id"])
        names.add(item["name"])
        added.append(item)

    json.dump(rows, open(res_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("resources total:", len(rows), "added:", len(added))

    db_path = os.path.join(BASE, "sichuan_terrain.db")
    conn = sqlite3.connect(db_path)
    ele = {}
    ele_path = os.path.join(DATA, "elevation_cache.json")
    if os.path.exists(ele_path):
        ele = json.load(open(ele_path, encoding="utf-8"))
    cur = conn.cursor()
    n = 0
    for item in added:
        cur.execute(
            "INSERT OR IGNORE INTO resources "
            "(id,name,cat,city,level,lon,lat,ele,dem_ele,tags,intro) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"], item["name"], item["cat"], item.get("city", ""),
                item.get("level", ""), item["lon"], item["lat"],
                item.get("ele"), ele.get(item["id"]),
                "、".join(item.get("tags") or []), item.get("intro", ""),
            ),
        )
        n += cur.rowcount
    conn.commit()
    print("db inserted:", n,
          "db total:", cur.execute("SELECT COUNT(*) FROM resources").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

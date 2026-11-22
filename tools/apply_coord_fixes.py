# -*- coding: utf-8 -*-
"""把经 OSM / DEM 校核后确认的资源坐标写回 resources.json。

每个条目都给出了校核依据（OSM 同名要素或 DEM 邻域高程），便于后续追溯。
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(BASE, "data", "resources.json")

# id: (lat, lon, 依据)
FIXES = {
    "cuokahai": (30.736, 100.1333, "OSM lake 措卡湖，DEM 3839m 与湖面 3800m 吻合"),
    "jianziwanshan": (30.0048, 100.8532, "OSM peak 剪子弯山"),
    "jiudingshan": (31.5589, 103.8414, "OSM peak 九顶山（4969m）"),
    "mahu": (28.4081, 103.7816, "OSM lake 马湖，DEM 1119m 与湖面 1100m 吻合"),
    "queershan": (31.786, 99.0721, "OSM peak 雀儿山（6168m）"),
    "wawushan": (29.6454, 102.9407, "OSM peak 瓦屋山（2800m）"),
    "huayingshan": (30.2312, 106.7752, "OSM peak 华蓥山"),
    "guangwushan": (32.5768, 106.7388, "OSM peak 光雾山"),
    "yaomei": (31.1064, 102.902, "OSM peak 幺妹峰（6250m）"),
    "xuebaoding": (32.6759, 103.8468, "OSM peak 雪宝顶（5588m）"),
    "xianairi": (28.395, 100.3508, "OSM peak 仙乃日（5998m）"),
    "yangmaiyong": (28.357, 100.3567, "OSM peak 央迈勇（6033m）"),
    "xianuoduoji": (28.385, 100.417, "OSM peak 夏诺多吉（5951m）"),
    "daxuetang": (30.7813, 102.9907, "OSM peak 大雪塘（5364m）"),
    "erlangshan": (29.8719, 102.2727, "OSM peak 二郎山（3437m）"),
    "xinluhai": (31.849, 99.1138, "OSM lake 新路海"),
    "wuxuhai": (29.1553, 101.4026, "OSM lake 伍须海子"),
    "mengdingshan": (30.084, 103.046, "OSM peak 蒙顶山（1456m）"),
    "fengtongzhai": (30.5542, 102.9242, "OSM protected_area 蜂桶寨保护区中心"),
    "genie": (29.80, 99.62, "DEM 邻域最高点 5580m，与格聂主峰区一致"),
    "dagu": (32.18, 102.78, "DEM 邻域最高点 4669m，对应达古冰川冰舌上方"),
    "balangshan": (30.87, 102.86, "巴郎山垭口实际位置（原坐标误落在四姑娘山北）"),
    "zimeiyakou": (29.57, 101.80, "贡嘎西坡子梅垭口，DEM 4186m"),
    "kasahu": (31.94, 99.55, "DEM 3499m 的湖盆，位于 G317 卡萨湖段"),
    "miyaluo": (31.66, 102.80, "DEM 2851m，与米亚罗镇（约 2700m）相符"),
    "bipenggou": (31.42, 103.02, "DEM 2827m，毕棚沟沟口朴头乡一带"),
}


def main():
    with open(PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    hit = 0
    for item in data:
        fix = FIXES.get(item["id"])
        if not fix:
            continue
        item["lat"], item["lon"] = fix[0], fix[1]
        hit += 1
        print("%-12s -> %.4f, %.4f  (%s)" % (item["name"], fix[0], fix[1], fix[2]))
    with open(PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("updated", hit, "of", len(FIXES), "| total", len(data))

    # 坐标变了，对应的高程缓存要重算
    cache_path = os.path.join(BASE, "data", "elevation_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
        for key in FIXES:
            cache.pop(key, None)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
        print("cleared", len(FIXES), "cached elevations")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""预取四川范围内的 Terrarium 高程瓦片，避免首屏渲染时逐张等待下载。

用法：python -X utf8 tools/prefetch_dem.py [最小z] [最大z]
"""
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import terrain_render  # noqa: E402

SOUTH, WEST, NORTH, EAST = 25.8, 97.1, 34.5, 108.8


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def main():
    zmin = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    zmax = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    jobs = []
    for z in range(zmin, zmax + 1):
        x0, y0 = tile_xy(NORTH, WEST, z)
        x1, y1 = tile_xy(SOUTH, EAST, z)
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                if 0 <= x < 2 ** z and 0 <= y < 2 ** z:
                    jobs.append((z, x, y))
    todo = [j for j in jobs if not os.path.exists(terrain_render.dem_path(*j))]
    print("z%d-%d: %d tiles, %d need download" % (zmin, zmax, len(jobs), len(todo)), flush=True)

    done = [0]

    def work(job):
        terrain_render.fetch_dem(*job)
        done[0] += 1
        if done[0] % 20 == 0:
            print("  %d/%d" % (done[0], len(todo)), flush=True)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, todo))
    print("prefetch done", flush=True)


if __name__ == "__main__":
    main()

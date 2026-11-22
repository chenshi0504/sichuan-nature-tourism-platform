# -*- coding: utf-8 -*-
"""四川自然旅游资源 · 本地服务

底图有三类：
  1) hyps      —— 由 Terrarium 高程瓦片现场渲染的「分层设色 + 山体晕渲」，是平台主底图；
  2) hillshade —— 纯灰阶晕渲，适合叠加资源点观察地形骨架；
  3) osm/topo  —— OpenStreetMap 系（CyclOSM / HOT）与 Esri 地形图，用于看路网与地名。
所有瓦片都由本机服务端代理并落盘缓存，浏览器只访问 127.0.0.1。

数据：data/resources.json（人工整理的四川自然旅游资源）、
      data/terrain_labels.json（OSM 山峰/湖泊/保护区注记）、
      data/rivers.geojson（主要河流几何）。
"""
import base64
import json
import math
import os
import re
import sqlite3
import threading
import urllib.request

from flask import Flask, Response, jsonify, render_template, request, send_file

try:  # 高程渲染依赖 numpy + Pillow；缺失时降级为 OSM 底图，至少页面还能打开
    import terrain_render
except Exception as _exc:  # noqa: BLE001
    terrain_render = None
    print("[WARN] 高程渲染模块不可用（%s），分层设色底图将回退为 OSM 瓦片。"
          "请用带 numpy/Pillow 的解释器启动（见 start.bat）。" % _exc)

TERRAIN_OK = terrain_render is not None
TILE_VERSION = getattr(terrain_render, "STYLE_VERSION", "v1") if TERRAIN_OK else "v1"

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8011"))
DB_PATH = os.path.join(BASE, "sichuan_terrain.db")
DATA = os.path.join(BASE, "data")

TILE_CACHE = os.path.join(BASE, "static", "tilecache")
BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# OpenStreetMap 系底图（本机到 tile.openstreetmap.org 不通，用 CyclOSM / HOT 顶上）
TILE_SOURCES = {
    "osm": [
        "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
    ],
    "topo": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
    ],
}
TILE_SUBDOMAINS = "abc"
TILE_UA = "SichuanTerrainAtlas/1.0 (local research tool)"
TILE_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CATEGORIES = [
    {"key": "heritage", "name": "世界遗产", "color": "#b0791f", "desc": "自然/双遗产与相关文化景观"},
    {"key": "scenic", "name": "自然景区", "color": "#2b8a63", "desc": "5A/4A 级自然类景区"},
    {"key": "glacier", "name": "冰川雪山", "color": "#5b6fc4", "desc": "5000 米级雪峰、冰川与观景垭口"},
    {"key": "water", "name": "湿地湖泊", "color": "#2f86b8", "desc": "高原湖泊、沼泽湿地与蛇曲"},
    {"key": "grassland", "name": "草原草甸", "color": "#7d9a2e", "desc": "高寒草甸与丘状高原牧场"},
    {"key": "gorge", "name": "峡谷河谷", "color": "#b4652f", "desc": "深切河谷与干热河谷"},
    {"key": "geopark", "name": "地质地貌", "color": "#7952a8", "desc": "地质公园、喀斯特与构造地貌"},
    {"key": "reserve", "name": "自然保护区", "color": "#3f7f57", "desc": "国家级自然保护区与遗产地"},
    {"key": "landform", "name": "地貌区", "color": "#8a8171", "desc": "省级地貌单元（大字注记）"},
]
CAT_KEYS = {c["key"] for c in CATEGORIES}

# 21 个市州驻地，用于在地图上提供空间参照（不参与资源统计）
CITIES_XY = [
    ("成都", 104.066, 30.572, 1), ("绵阳", 104.742, 31.464, 2), ("德阳", 104.398, 31.128, 2),
    ("南充", 106.110, 30.795, 2), ("达州", 107.502, 31.209, 2), ("广安", 106.633, 30.456, 3),
    ("遂宁", 105.573, 30.533, 3), ("资阳", 104.629, 30.122, 3), ("内江", 105.058, 29.580, 3),
    ("自贡", 104.779, 29.339, 3), ("泸州", 105.443, 28.889, 2), ("宜宾", 104.643, 28.752, 2),
    ("乐山", 103.766, 29.552, 2), ("眉山", 103.848, 30.075, 3), ("雅安", 103.001, 29.987, 2),
    ("攀枝花", 101.718, 26.582, 2), ("西昌", 102.267, 27.881, 2), ("康定", 101.963, 30.050, 2),
    ("马尔康", 102.221, 31.899, 2), ("广元", 105.829, 32.435, 2), ("巴中", 106.747, 31.858, 3),
]

app = Flask(__name__, static_folder="static", template_folder="templates")
if hasattr(app, "json"):
    app.json.ensure_ascii = False


@app.after_request
def _no_cache_html(resp):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype:
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ---------------------------------------------------------------- 数据库
SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cat TEXT NOT NULL,
    city TEXT,
    level TEXT,
    lon REAL NOT NULL,
    lat REAL NOT NULL,
    ele REAL,
    dem_ele REAL,
    tags TEXT,
    intro TEXT
);
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    ele REAL,
    minzoom REAL DEFAULT 9
);
CREATE TABLE IF NOT EXISTS rivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    geom TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rid TEXT NOT NULL,
    source TEXT NOT NULL,
    body TEXT NOT NULL,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_rid ON notes(rid);
"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_TERRAIN_CACHE = {}


def _terrain_cache():
    global _TERRAIN_CACHE
    if not _TERRAIN_CACHE:
        _TERRAIN_CACHE = _load_json("terrain_stats.json", {})
    return _TERRAIN_CACHE


def _load_json(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def init_db():
    conn = db()
    conn.executescript(SCHEMA)

    if conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0:
        rows = _load_json("resources.json", [])
        ele_cache = _load_json("elevation_cache.json", {})
        for item in rows:
            conn.execute(
                "INSERT OR IGNORE INTO resources "
                "(id,name,cat,city,level,lon,lat,ele,dem_ele,tags,intro) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"], item["name"], item["cat"], item.get("city", ""),
                    item.get("level", ""), item["lon"], item["lat"],
                    item.get("ele"), ele_cache.get(item["id"]),
                    "、".join(item.get("tags") or []), item.get("intro", ""),
                ),
            )
        conn.commit()
        print("[init] resources:", len(rows))

    if conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 0:
        labels = _load_json("terrain_labels.json", [])
        conn.executemany(
            "INSERT INTO labels (name,kind,lat,lon,ele,minzoom) VALUES (?,?,?,?,?,?)",
            [(l["name"], l["kind"], l["lat"], l["lon"], l.get("ele"),
              l.get("minZoom", 9)) for l in labels],
        )
        conn.commit()
        print("[init] labels:", len(labels))

    if conn.execute("SELECT COUNT(*) FROM rivers").fetchone()[0] == 0:
        fc = _load_json("rivers.geojson", {"features": []})
        rows = []
        for feat in fc.get("features", []):
            name = feat["properties"].get("name", "")
            for line in _split_lines(feat.get("geometry") or {}):
                rows.append((name, json.dumps(line, ensure_ascii=False)))
        conn.executemany("INSERT INTO rivers (name,geom) VALUES (?,?)", rows)
        conn.commit()
        print("[init] river segments:", len(rows))
    conn.close()


def _split_lines(geom):
    t = geom.get("type")
    if t == "LineString":
        return [geom["coordinates"]]
    if t == "MultiLineString":
        return geom["coordinates"]
    return []


# ---------------------------------------------------------------- 瓦片
def _proxy_tile(style, z, x, y):
    sources = TILE_SOURCES.get(style)
    if not sources or not (0 <= z <= 19) or x < 0 or y < 0:
        return Response(BLANK_PNG, mimetype="image/png", status=404)
    path = os.path.join(TILE_CACHE, style, str(z), str(x), "%d.png" % y)
    if not os.path.exists(path):
        data = None
        for tpl in sources:
            for sub in TILE_SUBDOMAINS:
                url = (tpl.replace("{s}", sub).replace("{z}", str(z))
                       .replace("{x}", str(x)).replace("{y}", str(y)))
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": TILE_UA, "Accept": "image/png"})
                    with TILE_OPENER.open(req, timeout=10) as resp:
                        data = resp.read()
                    if data and len(data) > 100:
                        break
                    data = None
                except Exception:  # noqa: BLE001
                    data = None
            if data:
                break
        if not data:
            return Response(BLANK_PNG, mimetype="image/png", status=404)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    return send_file(path, mimetype="image/png", max_age=86400)


@app.route("/tiles/<style>/<int:z>/<int:x>/<int:y>.png")
def tile(style, z, x, y):
    if style in ("hyps", "hillshade"):
        if not TERRAIN_OK:                       # 缺依赖时退回 OSM 瓦片，别让底图空白
            return _proxy_tile("osm", z, x, y)
        if not (0 <= z <= terrain_render.MAX_NATIVE_Z) or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
            return Response(BLANK_PNG, mimetype="image/png", status=404)
        try:
            path = terrain_render.cached_render(z, x, y, style)
        except Exception as exc:  # noqa: BLE001
            app.logger.warning("render failed %s %s/%s/%s: %s", style, z, x, y, exc)
            path = None
        if not path:
            return Response(BLANK_PNG, mimetype="image/png", status=404)
        return send_file(path, mimetype="image/png", max_age=86400)
    return _proxy_tile(style, z, x, y)


# ---------------------------------------------------------------- 页面
@app.route("/")
def index():
    return render_template(
        "index.html",
        tile_version=TILE_VERSION,
        terrain_ok=TERRAIN_OK,
        categories=CATEGORIES,
    )


# ---------------------------------------------------------------- 接口
def _row_to_resource(row, with_intro=True):
    tags = [t for t in (row["tags"] or "").split("、") if t]
    out = {
        "id": row["id"], "name": row["name"], "cat": row["cat"],
        "city": row["city"], "level": row["level"],
        "lon": row["lon"], "lat": row["lat"],
        "ele": row["ele"], "dem_ele": row["dem_ele"], "tags": tags,
    }
    if with_intro:
        out["intro"] = row["intro"]
    return out


@app.route("/api/meta")
def api_meta():
    conn = db()
    counts = {r["cat"]: r["n"] for r in conn.execute(
        "SELECT cat, COUNT(*) AS n FROM resources GROUP BY cat")}
    total = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
    labels = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    top = conn.execute(
        "SELECT name, COALESCE(ele, dem_ele) AS h FROM resources "
        "WHERE COALESCE(ele, dem_ele) IS NOT NULL ORDER BY h DESC LIMIT 1").fetchone()
    conn.close()
    highest = (top["h"], top["name"]) if top else (0, "")
    tiles = sum(len(files) for _, _, files in os.walk(os.path.join(TILE_CACHE, "dem"))) \
        if os.path.isdir(os.path.join(TILE_CACHE, "dem")) else 0
    return jsonify({
        "total": total,
        "counts": counts,
        "labels": labels,
        "highest": {"name": highest[1], "ele": highest[0]},
        "categories": CATEGORIES,
        "cities": [{"name": n, "lon": lon, "lat": lat, "rank": r} for n, lon, lat, r in CITIES_XY],
        "dem_tiles": tiles,
        "tile_version": TILE_VERSION,
        "terrain_ok": TERRAIN_OK,
    })


@app.route("/api/resources")
def api_resources():
    cat = (request.args.get("cat") or "").strip()
    conn = db()
    if cat and cat in CAT_KEYS:
        rows = conn.execute("SELECT * FROM resources WHERE cat=? ORDER BY name", (cat,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM resources ORDER BY name").fetchall()
    conn.close()
    return jsonify([_row_to_resource(r) for r in rows])


@app.route("/api/labels")
def api_labels():
    z = request.args.get("z", type=float)
    conn = db()
    rows = conn.execute("SELECT * FROM labels").fetchall()
    conn.close()
    out = []
    for r in rows:
        if z is not None and r["minzoom"] > z + 0.01:
            continue
        out.append({"name": r["name"], "kind": r["kind"], "lat": r["lat"],
                    "lon": r["lon"], "ele": r["ele"], "minZoom": r["minzoom"]})
    return jsonify(out)


@app.route("/api/rivers")
def api_rivers():
    conn = db()
    rows = conn.execute("SELECT name, geom FROM rivers").fetchall()
    conn.close()
    feats = [{"type": "Feature",
              "properties": {"name": r["name"]},
              "geometry": {"type": "LineString", "coordinates": json.loads(r["geom"])}}
             for r in rows]
    return jsonify({"type": "FeatureCollection", "features": feats})


@app.route("/api/boundary")
def api_boundary():
    return jsonify(_load_json("boundary.geojson", {"type": "FeatureCollection", "features": []}))


@app.route("/api/resource/<rid>")
def api_resource(rid):
    conn = db()
    row = conn.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    data = _row_to_resource(row)
    # 周边地形起伏：优先读预计算结果，缺省时才现算
    data["terrain"] = _terrain_cache().get(rid)
    if data["terrain"] is None and TERRAIN_OK:
        data["terrain"] = terrain_render.terrain_stats(row["lat"], row["lon"], radius_m=12000)
    near = conn.execute(
        "SELECT name, kind, lat, lon, ele FROM labels WHERE kind IN ('peak','ridge','lake','river','glacier')"
    ).fetchall()
    scored = []
    for r in near:
        d = _dist_km(row["lat"], row["lon"], r["lat"], r["lon"])
        if d < 60:
            scored.append((d, r["name"], r["kind"], r["ele"]))
    scored.sort()
    data["nearby"] = [{"name": n, "kind": k, "ele": e, "dist_km": round(d, 1)}
                      for d, n, k, e in scored[:6]]
    note = conn.execute("SELECT body, source FROM notes WHERE rid=?", (rid,)).fetchone()
    data["note"] = {"text": note["body"], "source": note["source"]} if note else None
    conn.close()
    return jsonify(data)


def _dist_km(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111.32
    dlon = (lon2 - lon1) * 111.32 * max(math.cos(math.radians(lat1)), 0.2)
    return (dlat ** 2 + dlon ** 2) ** 0.5


@app.route("/api/elevation")
def api_elevation():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat/lon required"}), 400
    if not (25.0 <= lat <= 35.2 and 96.5 <= lon <= 109.5):
        return jsonify({"ele": None, "outside": True})
    if not TERRAIN_OK:
        return jsonify({"ele": None, "error": "高程模块不可用"}), 503
    ele = terrain_render.sample(lat, lon)
    return jsonify({"lat": lat, "lon": lon, "ele": ele})


@app.route("/api/profile", methods=["POST"])
def api_profile():
    payload = request.get_json(silent=True) or {}
    pts = payload.get("points") or []
    clean = []
    for p in pts:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 25.0 <= lat <= 35.2 and 96.5 <= lon <= 109.5:
            clean.append((lat, lon))
    if len(clean) < 2:
        return jsonify({"error": "至少需要两个省域内的点"}), 400
    if len(clean) > 12:
        clean = clean[:12]
    if not TERRAIN_OK:
        return jsonify({"error": "高程模块不可用，请用带 numpy/Pillow 的解释器启动"}), 503
    data = terrain_render.profile(clean)
    eles = [d["ele"] for d in data if d["ele"] is not None]
    stats = {}
    if eles:
        stats = {"min": min(eles), "max": max(eles), "relief": round(max(eles) - min(eles), 0),
                 "length_km": data[-1]["dist_km"] if data else 0}
    return jsonify({"points": data, "stats": stats})


# ---------------------------------------------------------------- AI 解读
# 本机系统代理对 api.deepseek.com 不可用（连接直接被拒绝），这里强制直连
DS_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_deepseek_config():
    key = os.environ.get("DEEPSEEK_API_KEY") or ""
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not key:
        for path in (os.path.join(BASE, "config.json"),
                     os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")):
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                continue
            if path.endswith(".json"):
                try:
                    key = (json.loads(text) or {}).get("deepseek_api_key") or key
                except ValueError:
                    pass
            if not key:
                m = re.search(r"DEEPSEEK_API_KEY:\s*(\S+)", text)
                if m:
                    key = m.group(1)
    return key, base, model


def call_deepseek(prompt, timeout=90):
    key, base, model = load_deepseek_config()
    if not key:
        return None
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with DS_OPENER.open(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("deepseek failed: %s", exc)
        return None


def _parse_json(text):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _local_note(row, terrain):
    parts = []
    if row["ele"]:
        parts.append("峰顶标高 %d 米" % row["ele"])
    elif row["dem_ele"]:
        parts.append("DEM 高程约 %d 米" % row["dem_ele"])
    if terrain:
        parts.append("周边 ±%d 公里的高差达 %d 米（%d–%d 米）"
                     % (terrain["radius_km"], terrain["relief"], terrain["min"], terrain["max"]))
    if row["tags"]:
        parts.append("核心地貌要素是%s" % "、".join(row["tags"].split("、")[:3]))
    head = "%s（%s）%s" % (row["name"], row["city"] or "四川",
                          "，" + "，".join(parts) if parts else "")
    return (head + "。" + (row["intro"] or "") +
            " 可结合高程分层设色底图，观察它在四川地貌格局中的位置。")


@app.route("/api/ai/interpret", methods=["POST"])
def api_ai_interpret():
    payload = request.get_json(silent=True) or {}
    rid = payload.get("rid") or ""
    force = bool(payload.get("force"))
    conn = db()
    row = conn.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    if not force:
        cached = conn.execute("SELECT body, source FROM notes WHERE rid=?", (rid,)).fetchone()
        if cached:
            conn.close()
            return jsonify({"text": cached["body"], "source": cached["source"], "cached": True})

    terrain = _terrain_cache().get(rid)
    if terrain is None and TERRAIN_OK:
        terrain = terrain_render.terrain_stats(row["lat"], row["lon"], radius_m=12000)
    prompt = (
        "你是中国自然地理与山地旅游的研究者。请针对下面这个四川自然地景，写一段"
        "120-160 字的中文解读，把「地形地貌成因—可见景观—最佳观察方式」串起来，"
        "不要用营销腔，不要编造数据。只输出 JSON：{\"text\": \"...\"}。\n"
        "名称：%s\n类型：%s\n所在地：%s\n等级：%s\n海拔/高程：%s\n"
        "周边起伏：%s\n核心要素：%s\n已有简介：%s"
        % (row["name"], row["cat"], row["city"], row["level"],
           row["ele"] or row["dem_ele"] or "未知",
           json.dumps(terrain, ensure_ascii=False) if terrain else "未知",
           row["tags"], row["intro"])
    )
    parsed = _parse_json(call_deepseek(prompt))
    if parsed and parsed.get("text"):
        text, source = parsed["text"].strip(), "deepseek"
    else:
        text, source = _local_note(row, terrain), "local"
    conn.execute("INSERT OR REPLACE INTO notes (rid, source, body) VALUES (?,?,?)",
                 (rid, source, text))
    conn.commit()
    conn.close()
    return jsonify({"text": text, "source": source, "cached": False})


def _warm_dem_elevations():
    """后台补齐资源的 DEM 高程，避免首屏被大量采样请求拖慢。"""
    if not TERRAIN_OK:
        return
    try:
        conn = db()
        rows = conn.execute("SELECT id, lat, lon FROM resources WHERE dem_ele IS NULL").fetchall()
        for r in rows:
            ele = terrain_render.sample(r["lat"], r["lon"])
            if ele is not None:
                conn.execute("UPDATE resources SET dem_ele=? WHERE id=?", (ele, r["id"]))
        conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("warm dem failed: %s", exc)


if __name__ == "__main__":
    init_db()
    threading.Thread(target=_warm_dem_elevations, daemon=True).start()
    print("四川自然旅游资源 · http://127.0.0.1:%d" % PORT)
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)

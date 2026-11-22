# 四川自然旅游资源 · 地图探索平台

把四川的自然旅游资源叠在地形上看。Flask + 原生前端，无构建步骤，默认端口 **8011**。

## 为什么做这个

四川的自然旅游资源——山峰、湖泊、自然保护区、草原、峡谷——散落在各类攻略和资料里，
大多是平铺的文字列表，看不出"它在什么地形上、和周围的山川是什么关系"。

这个平台只做一件事：**给资源点配一张能读出地形起伏的底图**，让"海拔 7556 米的贡嘎"
和"海拔 500 米的丘陵"在同一张图上显出差别，而不是靠数字想象。

## 底图

三套可切换，都由本机服务端代理瓦片并落盘缓存，浏览器只访问 `127.0.0.1`：

| 类型 | 说明 |
|---|---|
| `hyps` | 由 Terrarium 高程瓦片现场渲染的「分层设色 + 山体晕渲」，主底图 |
| `hillshade` | 纯灰阶晕渲，适合叠加资源点观察地形骨架 |
| `osm` / `topo` | OSM 系（CyclOSM / HOT）与 Esri 地形图，用来看路网与地名 |

## 数据

| 文件 | 内容 |
|---|---|
| `data/resources.json` | 人工整理的四川自然旅游资源点（名称、经纬度、类型、简介） |
| `data/terrain_labels.json` | OSM 山峰 / 湖泊 / 保护区注记 |
| `data/rivers.geojson` | 主要河流几何 |
| `sichuan_terrain.db` | 上述数据的 SQLite 汇总，供服务端查询 |

## 运行

依赖 Python 3.11、Flask、numpy、Pillow：

```bash
pip install flask numpy pillow
python app.py
```

打开 <http://127.0.0.1:8011>。Windows 也可直接双击 `start.bat`（内部指定了带 numpy/Pillow 的解释器）。

> 缺 numpy / Pillow 时不会崩，但高程渲染模块会降级，分层设色底图退回 OSM 瓦片——
> 地形起伏就看不出来了，所以建议装齐依赖。

## 目录结构

```
app.py              服务端：瓦片代理、资源点接口、页面渲染
terrain_render.py   Terrarium 高程瓦片 → 分层设色 + 山体晕渲
static/             前端资源（app.js / style.css / vendor）
templates/          页面模板
data/               资源点、注记、河流几何
tools/              数据整理与抓取脚本
```

## 数据来源与授权

- 高程瓦片：Terrarium（AWS Open Data / Mapzen 系）
- 底图与注记：© OpenStreetMap contributors，ODbL
- 地形参考图：Esri World Shaded Relief

商用或再分发前请自行核对各数据源的许可条款。

## 已知限制

- `static/tilecache/` 是运行期生成的瓦片缓存（本机约 390 MB），**不纳入仓库**。
  首次浏览需要联网拉瓦片，之后命中本地缓存。想离线用，得先自行预热缓存。
- 资源点为人工整理，未逐点实地核验，坐标精度以"能定位到山/湖"为准。
- 只覆盖四川省域，不做路径规划与导航。

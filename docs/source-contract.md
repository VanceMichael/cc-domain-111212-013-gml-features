# 来源格式与业务语义

## 坐标语义

支持 WFS2/GML3.2 的本地投影：Point、LineString、Curve（LineStringSegment）、Polygon 的
exterior/interior、MultiGeometry/MultiPoint/MultiCurve/MultiSurface；`srsName` 与
`srsDimension` 可沿祖先继承，`pos`、`posList`、`coordinates` 均按声明维度切分。

轴顺序只从**已登记**的 CRS 条目查。EPSG:4326 的标准 URN 按 OGC 定义是“纬、经”，
CRS84 是“经、纬”；4326 的三维形式第三轴为椭球高。未登记的 `srsName`（例如
EPSG:3857、短写 `EPSG:4326`、本地自定义投影）不猜测、不联网查表、不做换算，整要素
阻塞并给出原因与响应节点位置。来源未声明 `srsName` 同样阻塞。

原始坐标永远按来源顺序保存；只有导出 GeoJSON 时才重排为 `[经度, 纬度, 可选高程]`，
并在要素属性中写明来源 `srsName`、轴顺序与维度，因此可倒推回原文。

## 引用

`xlink:href="#id"` 只解析同一响应内已索引的对象：

* 前向引用（目标在要素之后出现）在整页收完后统一解析；同页内未出现的目标判定为
  未解析，不能当作“稍后再看”。
* 同一几何对象被多个要素复用时只解码一次，`geometry_ref` 相同，`used_by` 列出全部
  使用要素；原始坐标与引用身份都保留。
* 外部引用（非 `#fragment`）不解引用、不联网。
* `gml:id` 重复时：原文完全一致可复用；内容冲突则阻塞所有受影响要素，本页不算完整。

## 要素隔离与页面完整性

单个要素内的坏几何（非数值坐标、维度不符、环未闭合、不支持的曲线段、CRS 冲突、
引用失败等）只阻塞该要素，其余要素照常采集。

`page.complete` 仅由两类事实决定：传输层是否完整收完、引用闭包是否闭合。响应在任意
字节处截断时，已闭合要素仍可查看，但整页一律标记不完整。`numberMatched` 可能为
`unknown`，它既不用来提前结束分页，也不用来推断是否还有下一页；`next` 仅原样报告，
单页采集不自动跟随。分页采集 `collect_pages` 只按 `next` 继续，任何一页不完整、非 200、
next 成环或超过页数上限都会停止并记录原因，残缺页不会被并入结果。

未解析的外部实体同样会让整页不完整：实体文本不能当成完整属性值。非 `#fragment` 的引用
永远不会发起文件或网络访问。GML 3.1 命名空间（`http://www.opengis.net/gml`）的几何不按
3.2 语义解释，按要素阻塞。

## 回溯

每个要素、每个几何都带 `source`：`tag`、`gml:id`、`start_byte`/`end_byte`、
`start_line`/`start_column`（列按字符计）与 `closed`。`app.py locate --id` 可按标识取回
原文片段或位置。

## 本地演练

`sampledata.py` 生成全部虚构夹具：`sample`（EPSG:4326 纬经 + 后向引用）、`crs84`
（经纬）、`dim3`（三维）、`hole`（两个洞的面）、`geometry`（点/线/曲线/多几何）、
`forward`（前向引用并被两个要素复用）、`broken`（六类坏要素隔离）、`duplicate`
（冲突重复 id）、`dangling`（悬空引用）、`invalid`（非要素集合）。生成不会下载资源。

本地 HTTP 演练器采用方法与原始路径作为路由键，值为按调用次数返回的响应数组，耗尽后
维持最后一项。响应可定义 status、headers、text/base64、require_headers、
chunk_bytes、disconnect_after。`fetch` 返回 `(status, headers, raw, complete)`，
`disconnect_after` 造成的短读会令 `complete=False`，采集时据此传入 `truncated`。

原始输入上限 16 MiB 是现有查看入口的保护值，不代表未来持续采集需一次读完整来源。
格式含义和截断错误不能被 HTTP 200 覆盖。

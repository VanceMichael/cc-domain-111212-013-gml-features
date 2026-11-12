# 来源格式与业务语义

支持 WFS2/GML3.2 的本地投影：Point、LineString、Polygon exterior/interior 与 MultiGeometry；srsDimension 可继承。轴序从明确 CRS 配置查，EPSG:4326 的标准 URN 是纬经，CRS84 是经纬；未登记 CRS 不做猜测或联网查表。GeoJSON 输出使用已证明的经纬坐标，不转换未知投影。xlink 仅解析已登记同源响应对象，重复 gml:id 内容冲突应阻塞受影响要素。

本地演练夹具由 `sampledata.py` 生成，均为虚构业务数据。`sample` 是当前可查看输入，`invalid` 是边界失败输入，其余用于对照来源变体。生成不会下载资源。

本地 HTTP 演练器采用方法与原始路径作为路由键，值为按调用次数返回的响应数组，耗尽后维持最后一项。响应可定义 status、headers、text/base64、require_headers、chunk_bytes、disconnect_after。每次请求保留方法、路径、头与正文摘要表示，便于核对实际访问；演练器只监听回环地址。

原始输入上限 16 MiB 是现有查看入口的保护值，不代表未来持续采集需一次读完整来源。格式含义和截断错误不能被 HTTP 200 覆盖。

# gml-features

城市配送项目所用 WFS 来源的要素与几何结构化采集：按来源声明的坐标语义解释 GML，
导出可追溯的 GeoJSON，并明确拒绝无法证明的部分。

## 当前能力

* `gml.py`：流式文档模型。保留每个元素的原始字节区间、gml:id/xml:id 索引与引用锚点，
  能在响应截断时区分已闭合与未闭合对象。
* `collector.py`：按 `srsName`/`srsDimension` 解释坐标，支持点、曲线、面（含多环洞）、
  多几何；解析同源 `xlink:href` 前向/后向引用并保持同一几何的身份；按要素隔离坏几何；
  给出页面完整性判断与 GeoJSON 导出。
* `source.py`：`inspect_bytes`（既有结构检查）、`collect_bytes`、`export_bytes`。
* `storage.py`：SQLite 留存原件、页面完整性与几何身份。
* `sampledata.py` / `transport.py` / `scenario.py`：可重复的本地夹具、回环演练源与请求记录。

坐标原则：只按登记过的 CRS 解释轴序；EPSG:4326 的 URN 是纬经，CRS84 是经纬。未声明或
未登记的来源一律不猜、不换算，GeoJSON 中保留 `null` 几何并给出原因与响应节点位置。
详见 `docs/source-contract.md`。

## 环境

Python 3.11 或以上，仅标准库，无需凭据和外部数据。使用容器时可执行 `docker build -t gml-features .`，依赖及镜像须在正式运行前准备。
运行入口、测试与演示均不安装包，不访问公网。数据库使用临时路径，不向代码目录写入业务文件。

## 测试与构建

构建工具版本固定在 `requirements-build.txt`，在环境准备阶段执行 `python3 -m pip install -r requirements-build.txt`；容器构建已包含此步骤。应用运行仍仅使用标准库，测试及演示不安装依赖。

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q app.py gml.py collector.py source.py sampledata.py storage.py transport.py scenario.py
python3 -m build --wheel --no-isolation
```

## 快速演示

```sh
python3 app.py demo        # 真实回环来源逐页采集并留存
python3 app.py demo-cases  # 逐项展示轴序、三维、带洞、前向引用与拒猜
python3 app.py demo-pages  # numberMatched 未知时按 next 取完三页
```

`demo` 启动本地来源、经 HTTP 取回五页、采集并写入临时数据库，退出后自动清理。演示覆盖
纬经/经纬顺序、三维坐标、带洞区域、前向引用复用与整页坏几何隔离；同一要素在输出中保留
`source` 节点位置，可回到原文核对。

## 单独采集与回溯

```sh
python3 app.py fixtures /tmp/gml-features-fixtures
python3 app.py inspect /tmp/gml-features-fixtures/sample.xml
python3 app.py collect /tmp/gml-features-fixtures/forward.xml
python3 app.py export  /tmp/gml-features-fixtures/hole.xml
python3 app.py locate  /tmp/gml-features-fixtures/forward.xml --id shared --form fragment
python3 app.py capture /tmp/gml-features-fixtures/sample.xml --database /tmp/gml-features.sqlite3 --source local-partner
python3 app.py list --database /tmp/gml-features.sqlite3
python3 app.py pages http://127.0.0.1:PORT/pages/page-1 --max-pages 20
```

`collect`/`export` 可加 `--truncated`，表示传输层确认响应未完整收完。`pages` 只跟随来源给出的
`next` 链接，遇到不完整页、非 200、分页成环或页数上限即停止并报告 `stopped`；它应只指向
已授权的本地或演练来源。生成夹具不会覆盖已有
文件。运行错误以 JSON 输出到标准错误并返回退出码 2；原始输入无效时不生成成功收件。内部
原件与任何对外展示副本应分开管理，不写入真实个人数据。

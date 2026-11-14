# 本地协议演练

`python3 scenario.py` 启动仅监听回环的业务来源，输出临时端口和可用路由。进程在前台运行，以 Ctrl-C 关闭。

`python3 scenario.py --export` 输出演练响应定义。路由：

| 路由 | 内容 |
| --- | --- |
| `GET /features` | CRS84 经纬点，分块返回 |
| `GET /features-crs84` | 同上，默认分块 |
| `GET /features-latlon` | EPSG:4326 纬经点 + 后向引用 |
| `GET /features-3d` | 三维位置 |
| `GET /features-hole` | 两个洞的面 |
| `GET /features-forward` | 前向引用，同一几何被两个要素复用 |
| `GET /features-broken` | 六类要素级坏几何 |
| `GET /features-truncated` | 传输层在页面中途断开 |
| `GET /features-rate-limited` | 首次 429 + `Retry-After`，再次 200 |
| `GET /pages/page-1` → `page-3` | `numberMatched="unknown"` 但 `next` 明确的分页 |

可按 `docs/source-contract.md` 在独立副本增加乱序、截断、失败或来源更新情形。响应数组顺次消耗并保持最后状态；不会调用真实第三方系统。

请求者可以在测试中用 `from scenario import scenario` 和 `ReplaySource(scenario())` 获得同样来源并检查 requests，避免固定端口冲突。`fetch` 返回四元组，最后一位表示是否完整收完；`/features-truncated` 必须为 `False`。

分页演练：

```sh
python3 app.py demo-pages                                   # 内置三页，全程 numberMatched 未知
python3 scenario.py --export > /tmp/routes.json             # 需要手工试其它地址时
```

`collect_pages` 只在收到 `next` 时继续，遇到截断页、非 200、分页成环或页数上限即停止并
记录 `stopped`，不把残缺页并入结果。

标准演练顺序是先准备依赖，再运行 `python3 -m unittest discover -s tests -v`、构建命令和 `python3 app.py demo`。演示逐页走真实 HTTP 与解析：轴序、三维、带洞、前向引用四页可转换，`broken.xml` 一页逐要素隔离并整页拒绝转换。另可用 `python3 app.py demo-cases` 查看含重复 id 与悬空引用的对照结果。演练只选有限输入，九十秒内完成。

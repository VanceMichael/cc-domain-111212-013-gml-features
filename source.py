"""来源检查与结构化采集入口。

`inspect_bytes` 只列出带标识的节点，是既有结构检查的兼容视图。
`collect_bytes` 解析 WFS/GML 要素与几何，返回带坐标语义、引用身份和页面完整性
判断的结构化结果。`export_bytes` 在结构化结果之上按已证明的轴顺序导出 GeoJSON。
`collect_pages` 按响应中的 next 链接继续取页；numberMatched 未知也不影响继续，
但任何一页不完整就立即停止，不把残缺页拼进结果。
"""

from urllib.parse import urljoin

from gml import Document
from collector import Collector, to_geojson


def inspect_bytes(data):
    """既有结构检查：列出响应中带 gml:id 的节点。"""
    document = Document.parse(data)
    if document.root is None or document.root.tag != 'http://www.opengis.net/wfs/2.0\x1fFeatureCollection':
        raise ValueError('不是 WFS 2.0 要素集合')
    rows = []
    for node in document.nodes:
        if node.id:
            rows.append({'id': node.id, 'tag': node.tag, 'srs': node.attrs.get('srsName')})
    return rows


def collect_bytes(data, crs=None, truncated=False):
    """结构化采集一页响应。`truncated` 由调用方按传输层是否完整收完给出。"""
    document = Document.parse(data, truncated=truncated)
    collector = Collector(document, crs=crs)
    return collector.collect()


def export_bytes(data, crs=None, truncated=False):
    """结构化采集并导出 GeoJSON；不能转换的要素保留原因与响应节点位置。"""
    return to_geojson(collect_bytes(data, crs=crs, truncated=truncated))


def collect_pages(fetch_page, first_url, max_pages=100, crs=None):
    """逐页取回并采集。

    * 继续的条件是响应给出了 next 链接，与 numberMatched 是否已知无关；
    * 一页不完整（截断、引用未闭合）就停止，并在结果中标明停止原因，不拼接残缺页；
    * 非 200、分页成环或超过页数上限同样停止并给出原因。
    """
    if max_pages < 1:
        raise ValueError('max_pages 至少为 1')
    pages = []
    url = first_url
    seen = set()
    stopped = None
    requests = 0
    while url is not None:
        if url in seen:
            stopped = dict(code='pagination-cycle', url=url)
            break
        if len(pages) >= max_pages:
            stopped = dict(code='page-limit', limit=max_pages, url=url)
            break
        seen.add(url)
        requests += 1
        status, headers, raw, complete = fetch_page(url)
        if status != 200:
            stopped = dict(code='http-status', status=status, url=url)
            break
        collection = collect_bytes(raw, crs=crs, truncated=not complete)
        exported = to_geojson(collection)
        pages.append(dict(url=url, collection=collection, geojson=exported))
        if not collection['page']['complete']:
            stopped = dict(code='incomplete-page', url=url,
                           reasons=[reason['code'] for reason in
                                    collection['page']['reasons']])
            break
        following = collection['page']['next']
        url = urljoin(url, following) if following else None
    return dict(pages=pages, requests=requests, stopped=stopped,
                number_matched=[page['collection']['page']['number_matched']
                                for page in pages],
                note='分页由 next 链接驱动；numberMatched 只原样报告，不用于提前结束')

import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile

from source import collect_bytes, collect_pages, export_bytes, inspect_bytes
from sampledata import samples
from storage import Archive
from transport import ReplaySource, fetch

MAX_INPUT = 16*1024*1024


def read_input(path):
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_INPUT+1)
    if len(data) > MAX_INPUT:
        raise ValueError('输入超过接收限制')
    return data


def demo():
    """本地起真实来源，逐页取回并采集；每页都实际经 HTTP 与解析，不用预录日志代替。"""
    fixtures = samples()
    order = ['crs84.xml', 'dim3.xml', 'hole.xml', 'forward.xml', 'broken.xml']
    routes = {'GET /features/' + name: [dict(base64=base64.b64encode(fixtures[name]).decode(),
                                             chunk_bytes=7)]
              for name in order}
    reports = []
    with tempfile.TemporaryDirectory() as directory, ReplaySource(routes) as server:
        with Archive(Path(directory)/'archive.sqlite3') as archive:
            for name in order:
                status, _, raw, complete = fetch(server.url + '/features/' + name)
                if status != 200:
                    raise ValueError('来源请求失败：' + name)
                collected = collect_bytes(raw, truncated=not complete)
                exported = export_bytes(raw, truncated=not complete)
                archive.save('local-demo', raw, collected['features'], collected)
                reports.append(dict(
                    input=name, status=status, bytes=len(raw), transport_complete=complete,
                    page=dict(complete=collected['page']['complete'],
                              collected=collected['page']['collected'],
                              blocked=collected['page']['blocked'],
                              reasons=collected['page']['reasons']),
                    features=[dict(id=feature['id'], status=feature['status'],
                                   crs=feature.get('crs') and feature['crs']['axis_order'],
                                   geometry=geo['geometry'],
                                   reason=geo.get('reason'))
                              for feature, geo in zip(collected['features'],
                                                      exported['features'])],
                    converted=exported['converted'],
                    not_converted=exported['not_converted']))
            return dict(demo=reports, captures=len(archive.list()),
                        requests=len(server.requests))
    return None


def demo_cases():
    """把演示需要覆盖的来源变体逐项展示：轴序、三维、带洞、前向引用与拒猜。"""
    fixtures = samples()
    cases = ['sample.xml', 'crs84.xml', 'dim3.xml', 'hole.xml', 'forward.xml',
             'broken.xml', 'duplicate.xml', 'dangling.xml']
    report = []
    for name in cases:
        collected = collect_bytes(fixtures[name])
        exported = export_bytes(fixtures[name])
        report.append(dict(
            input=name,
            page=dict(complete=collected['page']['complete'],
                      reasons=collected['page']['reasons'],
                      number_matched=collected['page']['number_matched']),
            features=[dict(id=feature['id'], status=feature['status'],
                           reference=feature.get('reference'),
                           axis_order=feature.get('crs') and feature['crs']['axis_order'],
                           geometry=geo['geometry'],
                           reason=geo.get('reason'))
                      for feature, geo in zip(collected['features'], exported['features'])],
            converted=exported['converted'],
            not_converted=exported['not_converted']))
    return report


def demo_pages():
    """按 next 链接连续取页。numberMatched 全程未知，仍必须取完三页。"""
    from sampledata import PAGES
    routes = {'GET /pages/' + path: [dict(base64=base64.b64encode(raw).decode(),
                                          chunk_bytes=9)]
              for path, raw in PAGES}
    with ReplaySource(routes) as server:
        result = collect_pages(fetch, server.url + '/pages/page-1')
    return dict(
        requests=result['requests'], stopped=result['stopped'],
        number_matched=result['number_matched'],
        pages=[dict(url=page['url'],
                    matched=page['collection']['page']['number_matched'],
                    returned=page['collection']['page']['number_returned'],
                    complete=page['collection']['page']['complete'],
                    features=[feature['id'] for feature in page['geojson']['features']],
                    coordinates=[feature['geometry']['coordinates']
                                 for feature in page['geojson']['features']
                                 if feature['geometry']])
              for page in result['pages']])


def main(argv=None):
    parser = argparse.ArgumentParser(description='来源检查、结构化采集与 GeoJSON 导出')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'capture', 'collect', 'export'):
        command = commands.add_parser(name)
        command.add_argument('path')
        if name == 'capture':
            command.add_argument('--database', required=True)
            command.add_argument('--source', required=True)
        if name in ('collect', 'export'):
            command.add_argument('--truncated', action='store_true',
                                 help='传输层确认响应未完整收完时使用')
    listing = commands.add_parser('list')
    listing.add_argument('--database', required=True)
    locate = commands.add_parser('locate', help='回到响应中的原始节点')
    locate.add_argument('path')
    locate.add_argument('--id', required=True)
    locate.add_argument('--occurrence', type=int, default=0)
    locate.add_argument('--form', choices=('xml', 'fragment', 'position'), default='xml')
    fixtures = commands.add_parser('fixtures')
    fixtures.add_argument('directory')
    commands.add_parser('demo')
    commands.add_parser('demo-cases')
    commands.add_parser('demo-pages')
    pages = commands.add_parser('pages', help='按来源 next 链接连续采集')
    pages.add_argument('url', help='第一页地址；只应指向已授权的本地或演练来源')
    pages.add_argument('--max-pages', type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            result = demo()
        elif args.command == 'demo-cases':
            result = demo_cases()
        elif args.command == 'demo-pages':
            result = demo_pages()
        elif args.command == 'pages':
            walked = collect_pages(fetch, args.url, max_pages=args.max_pages)
            result = dict(requests=walked['requests'], stopped=walked['stopped'],
                          number_matched=walked['number_matched'],
                          pages=[dict(url=page['url'], geojson=page['geojson'])
                                 for page in walked['pages']])
        elif args.command == 'fixtures':
            destination = Path(args.directory)
            destination.mkdir(parents=True, exist_ok=True)
            for name, raw in samples().items():
                path = destination/name
                if path.exists():
                    raise ValueError('不覆盖已有夹具文件：'+name)
                path.write_bytes(raw)
            result = dict(files=sorted(samples()))
        elif args.command == 'list':
            with Archive(args.database) as archive:
                result = archive.list()
        elif args.command == 'locate':
            from gml import Document
            document = Document.parse(read_input(args.path))
            result = document.locate(args.id, occurrence=args.occurrence, form=args.form)
        else:
            raw = read_input(args.path)
            if args.command == 'inspect':
                result = inspect_bytes(raw)
            elif args.command == 'collect':
                result = collect_bytes(raw, truncated=args.truncated)
            elif args.command == 'export':
                result = export_bytes(raw, truncated=args.truncated)
            else:
                rows = inspect_bytes(raw)
                with Archive(args.database) as archive:
                    result = dict(capture_id=archive.save(args.source, raw, rows),
                                  rows=len(rows))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(error=type(error).__name__, reason=str(error)),
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

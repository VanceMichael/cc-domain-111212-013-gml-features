import base64
import json
from sampledata import PAGES, samples


def response(raw, status=200, headers=None, chunk_bytes=3, **options):
    return dict(base64=base64.b64encode(raw).decode(), status=status,
                headers=headers or {}, chunk_bytes=chunk_bytes, **options)


def scenario():
    """本地来源演练：每页都按真实 HTTP 分块返回，最后一页故意截断。"""
    fixtures = samples()
    routes = {}
    routes['GET /features'] = [response(fixtures['crs84.xml'], status=200)]
    routes['GET /features-crs84'] = [response(fixtures['crs84.xml'], status=200)]
    routes['GET /features-latlon'] = [response(fixtures['sample.xml'], chunk_bytes=5)]
    routes['GET /features-3d'] = [response(fixtures['dim3.xml'], chunk_bytes=2)]
    routes['GET /features-hole'] = [response(fixtures['hole.xml'], chunk_bytes=7)]
    routes['GET /features-forward'] = [response(fixtures['forward.xml'], chunk_bytes=4)]
    routes['GET /features-broken'] = [response(fixtures['broken.xml'], chunk_bytes=11)]
    # 传输层在页面中途断开：客户端只能算收到不完整一页。
    routes['GET /features-truncated'] = [response(
        fixtures['forward.xml'], disconnect_after=len(fixtures['forward.xml']) - 60)]
    # 第一页返回 429 并要求退避；请求方不得把非 200 当成空页或完整页。
    routes['GET /features-rate-limited'] = [
        response(b'cooldown', status=429, headers={'Retry-After': '30'}),
        response(fixtures['crs84.xml'])]
    # numberMatched 未知但 next 明确：三页必须全部取回。
    for path, raw in PAGES:
        routes['GET /pages/' + path] = [response(raw, chunk_bytes=5)]
    return routes


def main():
    import argparse
    from transport import ReplaySource
    parser = argparse.ArgumentParser(description='来源协议本地演练入口')
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    routes = scenario()
    if args.export:
        print(json.dumps(routes, ensure_ascii=False, sort_keys=True))
        return
    with ReplaySource(routes) as server:
        print(json.dumps({'url': server.url, 'routes': list(routes)},
                         ensure_ascii=False), flush=True)
        try:
            server.thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

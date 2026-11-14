import base64
from collections import Counter
from contextlib import AbstractContextManager
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

class ReplaySource(AbstractContextManager):
    def __init__(self, routes):
        self.routes = routes
        self.requests = []
        self.counts = Counter()
        self.lock = Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def handle_request(self):
                length = int(self.headers.get('Content-Length', '0'))
                if length > 1024 * 1024:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                with owner.lock:
                    key = self.command + ' ' + self.path
                    index = owner.counts[key]
                    owner.counts[key] += 1
                    owner.requests.append(dict(method=self.command, path=self.path,
                                               headers=dict(self.headers), body=body.hex()))
                    choices = owner.routes.get(key)
                    response = choices[min(index, len(choices)-1)] if choices else dict(status=404, text='未登记路由')
                expected = response.get('require_headers', {})
                if any(self.headers.get(name) != value for name, value in expected.items()):
                    self.send_error(412)
                    return
                payload = base64.b64decode(response['base64']) if 'base64' in response else response.get('text', '').encode()
                self.send_response(response.get('status', 200))
                for name, value in response.get('headers', {}).items():
                    self.send_header(name, str(value))
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                width = max(1, response.get('chunk_bytes', len(payload) or 1))
                cutoff = response.get('disconnect_after', len(payload))
                try:
                    for position in range(0, min(cutoff, len(payload)), width):
                        self.wfile.write(payload[position:min(position+width, cutoff)])
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                if cutoff < len(payload):
                    self.close_connection = True

            do_GET = handle_request
            do_POST = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)

    @property
    def url(self):
        return 'http://127.0.0.1:' + str(self.server.server_port)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

def fetch(url, headers=None, max_bytes=16*1024*1024):
    """返回 (状态, 头, 原始字节, 是否完整收完)。

    非 200 或读取中途断开时仍返回已收到的字节，但 complete 为 False；调用方据此
    判定页面不完整，而不是让解析成功与否替传输层说话。
    """
    request = Request(url, headers=headers or {})
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    complete = True
    with response:
        chunks = []
        remaining = max_bytes + 1
        try:
            while remaining > 0:
                chunk = response.read(min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except (ConnectionResetError, IncompleteRead) as error:
            complete = False
        raw = b''.join(chunks)
        if len(raw) > max_bytes:
            raise ValueError('响应超过接收限制')
        expected = response.headers.get('Content-Length')
        if complete and expected is not None and expected.isdigit() \
                and int(expected) != len(raw):
            complete = False
        return response.status, dict(response.headers), raw, complete

def main():
    import argparse
    parser = argparse.ArgumentParser(description='本地来源演练服务')
    parser.add_argument('routes')
    args = parser.parse_args()
    with open(args.routes, encoding='utf8') as handle:
        routes = json.load(handle)
    with ReplaySource(routes) as server:
        print(server.url, flush=True)
        try:
            server.thread.join()
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    main()

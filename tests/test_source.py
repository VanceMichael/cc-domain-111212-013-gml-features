import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import app
from sampledata import samples
from source import inspect_bytes
from storage import Archive
from transport import ReplaySource, fetch

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = samples()
        self.name = next(name for name in self.fixtures if name.startswith('sample.'))

    def test_domain_sample(self):
        data = self.fixtures[self.name]
        result = inspect_bytes(data)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1]['id'], 'p1')
        self.assertEqual(result[-1]['srs'], 'urn:ogc:def:crs:EPSG::4326')

    def test_invalid_sample(self):
        invalid = next(data for name,data in self.fixtures.items() if name.startswith('invalid.'))
        with self.assertRaises(Exception):
            inspect_bytes(invalid)

    def test_sample_determinism(self):
        self.assertEqual(self.fixtures, samples())
        self.assertEqual(inspect_bytes(self.fixtures[self.name]), inspect_bytes(self.fixtures[self.name]))

    def test_capture_is_content_scoped_and_durable(self):
        data = self.fixtures[self.name]
        rows = inspect_bytes(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'archive.sqlite3'
            with Archive(path) as archive:
                first = archive.save('source-a', data, rows)
                self.assertEqual(archive.save('source-a', data, rows), first)
                self.assertNotEqual(archive.save('source-b', data, rows), first)
                self.assertEqual(archive.raw(first), data)
            with Archive(path) as archive:
                self.assertEqual(len(archive.list()), 2)
                self.assertEqual(archive.list()[0]['rows'], rows)

    def test_empty_source_rejected_without_writing(self):
        with Archive(':memory:') as archive:
            with self.assertRaises(ValueError):
                archive.save(' ', b'raw', [])
            self.assertEqual(archive.list(), [])

    def test_real_http_and_chunk_boundaries(self):
        data = self.fixtures[self.name]
        route = dict(base64=base64.b64encode(data).decode(), chunk_bytes=1)
        with ReplaySource({'GET /source':[route]}) as server:
            status, headers, raw, complete = fetch(server.url+'/source')
            self.assertEqual(status, 200)
            self.assertTrue(complete)
            self.assertEqual(raw, data)
            self.assertEqual(inspect_bytes(raw), inspect_bytes(data))
            self.assertEqual(len(server.requests), 1)

    def test_http_status_and_limit(self):
        with ReplaySource({'GET /sequence':[dict(status=429,text='cooldown'),dict(text='ok')]}) as server:
            self.assertEqual(fetch(server.url+'/sequence')[0], 429)
            self.assertEqual(fetch(server.url+'/sequence')[2], b'ok')
            with self.assertRaises(ValueError):
                fetch(server.url+'/sequence', max_bytes=1)

    def test_transport_reports_incomplete_page(self):
        data = self.fixtures[self.name]
        with ReplaySource({'GET /cut':[dict(base64=base64.b64encode(data).decode(),
                                            disconnect_after=len(data)-40)]}) as server:
            status, headers, raw, complete = fetch(server.url+'/cut')
        self.assertEqual(status, 200)
        self.assertFalse(complete)
        self.assertLess(len(raw), len(data))

    def test_cli_capture_list_and_bad_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/self.name
            path.write_bytes(self.fixtures[self.name])
            database = str(Path(directory)/'store.sqlite3')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['capture',str(path),'--database',database,'--source','cli']), 0)
            self.assertGreater(json.loads(output.getvalue())['rows'], 0)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['list','--database',database]), 0)
            self.assertEqual(len(json.loads(output.getvalue())), 1)
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(app.main(['inspect', str(path)+'.missing']), 2)
            self.assertIn('FileNotFoundError', error.getvalue())

    def test_demo_pages_continues_while_number_matched_unknown(self):
        report = app.demo_pages()
        self.assertEqual(report['requests'], 3)
        self.assertIsNone(report['stopped'])
        self.assertEqual(report['number_matched'], ['unknown', 'unknown', 'unknown'])
        self.assertEqual([page['features'] for page in report['pages']],
                         [['p1'], ['p2'], ['p3']])
        self.assertTrue(all(page['complete'] for page in report['pages']))

    def test_demo_reaches_source_and_archive(self):
        report = app.demo()
        self.assertEqual(report['captures'], len(report['demo']))
        self.assertEqual(report['requests'], len(report['demo']))
        names = {case['input'] for case in report['demo']}
        self.assertEqual(names, {'crs84.xml', 'dim3.xml', 'hole.xml',
                                 'forward.xml', 'broken.xml'})
        for case in report['demo']:
            self.assertEqual(case['status'], 200)
            self.assertTrue(case['transport_complete'])
            self.assertIn('page', case)
        # 演示同时覆盖可转换与明确拒绝转换两类结果。
        self.assertGreater(sum(case['converted'] for case in report['demo']), 0)
        self.assertGreater(sum(len(case['not_converted']) for case in report['demo']), 0)

if __name__ == '__main__':
    unittest.main()

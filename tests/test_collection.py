import base64
import json
import tempfile
import unittest
from pathlib import Path

from scenario import scenario
from source import collect_bytes, collect_pages, export_bytes
from sampledata import samples
from storage import Archive
from transport import ReplaySource, fetch

WFS_NS = 'xmlns:wfs="http://www.opengis.net/wfs/2.0"'


def collection(body, **attributes):
    declared = ' '.join('%s="%s"' % item for item in attributes.items())
    return (('<wfs:FeatureCollection %s xmlns:gml="http://www.opengis.net/gml/3.2"'
             ' xmlns:a="urn:areas" xmlns:xlink="http://www.w3.org/1999/xlink" %s>%s'
             '</wfs:FeatureCollection>') % (WFS_NS, declared, body)).encode()


def feature(identifier, geometry):
    return ('<wfs:member><a:Area gml:id="%s"><a:shape>%s</a:shape></a:Area></wfs:member>'
            % (identifier, geometry))


CRS84 = 'urn:ogc:def:crs:OGC:1.3:CRS84'
EPSG4326 = 'urn:ogc:def:crs:EPSG::4326'


class AxisOrderTests(unittest.TestCase):
    def test_epsg_4326_is_latitude_longitude(self):
        raw = collection(feature('latlon', '<gml:Point srsName="%s"><gml:pos>31 121</gml:pos>'
                                         '</gml:Point>' % EPSG4326))
        collected = collect_bytes(raw)
        exported = export_bytes(raw)
        self.assertEqual(collected['features'][0]['crs']['axis_order'], ['lat', 'lon'])
        # 来源 31 121 是“纬 31、经 121”，GeoJSON 必须写成 [经, 纬]。
        self.assertEqual(exported['features'][0]['geometry']['coordinates'], [121.0, 31.0])
        self.assertEqual(exported['not_converted'], [])

    def test_crs84_is_longitude_latitude(self):
        raw = collection(feature('lonlat', '<gml:Point srsName="%s"><gml:pos>121 31</gml:pos>'
                                          '</gml:Point>' % CRS84))
        collected = collect_bytes(raw)
        exported = export_bytes(raw)
        self.assertEqual(collected['features'][0]['crs']['axis_order'], ['lon', 'lat'])
        self.assertEqual(exported['features'][0]['geometry']['coordinates'], [121.0, 31.0])

    def test_same_numbers_different_declared_axis_order(self):
        latlon = collection(feature('x', '<gml:Point srsName="%s"><gml:pos>31 121</gml:pos>'
                                         '</gml:Point>' % EPSG4326))
        lonlat = collection(feature('x', '<gml:Point srsName="%s"><gml:pos>31 121</gml:pos>'
                                         '</gml:Point>' % CRS84))
        first = export_bytes(latlon)['features'][0]['geometry']['coordinates']
        second = export_bytes(lonlat)['features'][0]['geometry']['coordinates']
        self.assertEqual(first, [121.0, 31.0])
        self.assertEqual(second, [31.0, 121.0])
        # 后者若被当作真实位置会落到另一个半球附近；采集结果明确保留来源原始坐标。
        collected = collect_bytes(lonlat)
        value = collected['geometries'][0]['value']
        self.assertEqual(value['order'], 'source')
        self.assertEqual(value['position']['raw'], '31 121')
        self.assertEqual(value['position']['values'], [31.0, 121.0])

    def test_unregistered_crs_is_never_guessed(self):
        for srs in ('urn:ogc:def:crs:EPSG::3857', 'EPSG:4326', 'urn:ogc:def:crs:EPSG::4490'):
            raw = collection(feature('x', '<gml:Point srsName="%s"><gml:pos>31 121</gml:pos>'
                                             '</gml:Point>' % srs))
            collected = collect_bytes(raw)
            exported = export_bytes(raw)
            item = collected['features'][0]
            self.assertEqual(item['status'], 'blocked', srs)
            self.assertEqual(item['reason']['code'], 'unknown-crs', srs)
            self.assertIsNone(exported['features'][0]['geometry'], srs)
            self.assertEqual(exported['features'][0]['reason']['code'], 'unknown-crs')
            self.assertEqual(exported['not_converted'][0]['id'], 'x')

    def test_unknown_crs_fixture_covers_three_unprovable_sources(self):
        exported = export_bytes(samples()['unknown.xml'])
        self.assertEqual(exported['converted'], 0)
        self.assertEqual(len(exported['features']), 3)
        self.assertTrue(all(feature['geometry'] is None for feature in exported['features']))
        self.assertEqual([feature['reason']['code'] for feature in exported['features']],
                         ['unknown-crs', 'unknown-crs', 'missing-crs'])
        # 采集结果仍保留来源原始坐标，只是不声称其位置语义。
        collected = collect_bytes(samples()['unknown.xml'])
        self.assertEqual(collected['geometries'][0]['value']['position']['raw'],
                         '13465233 3642037')

    def test_missing_srs_name_is_blocked(self):
        raw = collection(feature('x', '<gml:Point><gml:pos>31 121</gml:pos></gml:Point>'))
        exported = export_bytes(raw)
        self.assertIsNone(exported['features'][0]['geometry'])
        self.assertEqual(exported['features'][0]['reason']['code'], 'missing-crs')

    def test_srs_and_dimension_inherited_from_ancestor(self):
        raw = collection('<gml:Point gml:id="shared" srsName="%s" srsDimension="3">'
                         '<gml:pos>10 20 30</gml:pos></gml:Point>'
                         '<wfs:member><a:Area gml:id="child"><a:shape xlink:href="#shared"/>'
                         '</a:Area></wfs:member>' % EPSG4326)
        exported = export_bytes(raw)
        self.assertEqual(exported['features'][0]['properties']['source_crs']['axis_order'],
                         ['lat', 'lon', 'h'])
        self.assertEqual(exported['features'][0]['geometry']['coordinates'], [20.0, 10.0, 30.0])


class DimensionTests(unittest.TestCase):
    def test_three_dimensional_position(self):
        raw = collection(feature('p', '<gml:Point srsName="%s" srsDimension="3">'
                                      '<gml:pos>31.5 120.25 12.5</gml:pos></gml:Point>'
                                % EPSG4326))
        exported = export_bytes(raw)
        geometry = exported['features'][0]['geometry']
        self.assertEqual(geometry, dict(type='Point', coordinates=[120.25, 31.5, 12.5]))
        source = exported['features'][0]['properties']['source_crs']
        self.assertEqual(source['axis_order'], ['lat', 'lon', 'h'])
        self.assertEqual(source['dimension'], 3)

    def test_poslist_uses_declared_dimension(self):
        raw = collection(feature('p', '<gml:Point srsName="%s" srsDimension="2">'
                                      '<gml:pos>31 121</gml:pos></gml:Point>' % EPSG4326))
        self.assertEqual(export_bytes(raw)['features'][0]['geometry']['coordinates'],
                         [121.0, 31.0])

    def test_poslist_not_multiple_of_dimension_is_blocked(self):
        raw = collection(feature('p', '<gml:Polygon srsName="%s" srsDimension="3">'
                                      '<gml:exterior><gml:LinearRing><gml:posList>'
                                      '31 121 0 31 121.1 0 31.1 121.1 0 31 121'
                                      '</gml:posList></gml:LinearRing></gml:exterior>'
                                      '</gml:Polygon>' % EPSG4326))
        exported = export_bytes(raw)
        self.assertEqual(exported['features'][0]['reason']['code'], 'dimension-mismatch')
        self.assertIsNone(exported['features'][0]['geometry'])

    def test_non_numeric_coordinate_is_blocked(self):
        raw = collection(feature('p', '<gml:Point srsName="%s"><gml:pos>121 east</gml:pos>'
                                      '</gml:Point>' % CRS84))
        exported = export_bytes(raw)
        self.assertEqual(exported['features'][0]['reason']['code'], 'invalid-coordinate')


class GeometryTests(unittest.TestCase):
    def test_polygon_with_holes_is_not_flattened(self):
        raw = collection(feature('z', (
            '<gml:Polygon srsName="%s"><gml:exterior><gml:LinearRing><gml:posList>'
            '121 31 121.1 31 121.1 31.1 121 31.1 121 31'
            '</gml:posList></gml:LinearRing></gml:exterior>'
            '<gml:interior><gml:LinearRing><gml:posList>'
            '121.02 31.02 121.04 31.02 121.04 31.04 121.02 31.04 121.02 31.02'
            '</gml:posList></gml:LinearRing></gml:interior>'
            '<gml:interior><gml:LinearRing><gml:posList>'
            '121.06 31.06 121.08 31.06 121.08 31.08 121.06 31.08 121.06 31.06'
            '</gml:posList></gml:LinearRing></gml:interior></gml:Polygon>') % CRS84))
        geometry = export_bytes(raw)['features'][0]['geometry']
        self.assertEqual(geometry['type'], 'Polygon')
        self.assertEqual(len(geometry['coordinates']), 3)
        self.assertEqual(geometry['coordinates'][1][0], [121.02, 31.02])
        self.assertEqual(geometry['coordinates'][2][0], [121.06, 31.06])
        for ring in geometry['coordinates']:
            self.assertGreaterEqual(len(ring), 4)
            self.assertEqual(ring[0], ring[-1])

    def test_rings_from_fixture_preserve_each_hole(self):
        collected = collect_bytes(samples()['hole.xml'])
        value = collected['geometries'][0]['value']
        self.assertEqual(len(value['interiors']), 2)
        self.assertNotEqual(value['exterior'], value['interiors'][0])
        self.assertEqual(value['exterior'][0]['raw'], '121 31')

    def test_linestring_and_curve(self):
        raw = collection(
            feature('line', '<gml:LineString srsName="%s"><gml:posList>'
                            '1 2 3 4 5 6</gml:posList></gml:LineString>' % CRS84)
            + feature('curve', '<gml:Curve srsName="%s"><gml:segments>'
                               '<gml:LineStringSegment><gml:posList>7 8 9 10</gml:posList>'
                               '</gml:LineStringSegment></gml:segments></gml:Curve>' % CRS84))
        exported = export_bytes(raw)
        self.assertEqual(exported['features'][0]['geometry'],
                         dict(type='LineString', coordinates=[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]))
        self.assertEqual(exported['features'][1]['geometry'],
                         dict(type='LineString', coordinates=[[7.0, 8.0], [9.0, 10.0]]))

    def test_multi_geometry_including_reference(self):
        raw = collection(
            '<gml:Point gml:id="pt" srsName="%s"><gml:pos>1 2</gml:pos></gml:Point>' % CRS84
            + feature('multi', '<gml:MultiGeometry srsName="%s">'
                               '<gml:geometryMember xlink:href="#pt"/>'
                               '<gml:geometryMember><gml:Point><gml:pos>3 4</gml:pos>'
                               '</gml:Point></gml:geometryMember></gml:MultiGeometry>' % CRS84))
        exported = export_bytes(raw)
        self.assertEqual(exported['features'][0]['geometry'],
                         dict(type='MultiPoint', coordinates=[[1.0, 2.0], [3.0, 4.0]]))

    def test_unsupported_curve_segment_is_isolated(self):
        raw = collection(
            feature('arc', '<gml:Curve srsName="%s"><gml:segments><gml:Arc><gml:posList>'
                           '1 2 3 4 5 6</gml:posList></gml:Arc></gml:segments></gml:Curve>'
                    % CRS84)
            + feature('ok', '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos></gml:Point>' % CRS84))
        collected = collect_bytes(raw)
        self.assertEqual([item['status'] for item in collected['features']], ['blocked', 'go'])
        self.assertEqual(collected['features'][0]['reason']['code'], 'unsupported-curve-segment')
        self.assertEqual(collected['features'][1]['status'], 'go')
        self.assertTrue(collected['page']['complete'])

    def test_multi_curve_and_multi_surface(self):
        curve = collection(feature('c', (
            '<gml:MultiCurve srsName="%s">'
            '<gml:curveMember><gml:LineString><gml:posList>1 2 3 4</gml:posList>'
            '</gml:LineString></gml:curveMember>'
            '<gml:curveMember><gml:LineString><gml:posList>5 6 7 8</gml:posList>'
            '</gml:LineString></gml:curveMember></gml:MultiCurve>') % CRS84))
        self.assertEqual(export_bytes(curve)['features'][0]['geometry'],
                         dict(type='MultiLineString',
                              coordinates=[[[1.0, 2.0], [3.0, 4.0]],
                                           [[5.0, 6.0], [7.0, 8.0]]]))
        surface = collection(feature('s', (
            '<gml:MultiSurface srsName="%s">'
            '<gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing>'
            '<gml:posList>1 2 3 2 3 4 1 4 1 2</gml:posList></gml:LinearRing>'
            '</gml:exterior></gml:Polygon></gml:surfaceMember>'
            '<gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing>'
            '<gml:posList>5 6 7 6 7 8 5 8 5 6</gml:posList></gml:LinearRing>'
            '</gml:exterior></gml:Polygon></gml:surfaceMember>'
            '</gml:MultiSurface>') % CRS84))
        geometry = export_bytes(surface)['features'][0]['geometry']
        self.assertEqual(geometry['type'], 'MultiPolygon')
        self.assertEqual(len(geometry['coordinates']), 2)

    def test_nested_geometry_crs_conflict_is_blocked(self):
        raw = collection(feature('multi', (
            '<gml:MultiGeometry srsName="%s"><gml:geometryMember>'
            '<gml:Point><gml:pos>1 2</gml:pos></gml:Point></gml:geometryMember>'
            '<gml:geometryMember><gml:Point srsName="%s"><gml:pos>3 4</gml:pos></gml:Point>'
            '</gml:geometryMember></gml:MultiGeometry>') % (CRS84, EPSG4326)))
        collected = collect_bytes(raw)
        self.assertEqual(collected['features'][0]['reason']['code'], 'crs-conflict')


class ReferenceTests(unittest.TestCase):
    def test_forward_reference_resolved_after_page(self):
        raw = samples()['forward.xml']
        collected = collect_bytes(raw)
        self.assertEqual([item['status'] for item in collected['features']], ['go', 'go'])
        self.assertEqual(collected['features'][0]['geometry_ref'],
                         collected['features'][1]['geometry_ref'])
        self.assertEqual(len(collected['geometries']), 1)
        self.assertEqual(collected['geometries'][0]['used_by'], ['f1', 'f2'])
        self.assertEqual(collected['geometries'][0]['gml_id'], 'shared')
        self.assertTrue(collected['page']['complete'])

    def test_reused_geometry_keeps_identity_and_source_coordinates(self):
        collected = collect_bytes(samples()['forward.xml'])
        exported = export_bytes(samples()['forward.xml'])
        self.assertEqual(exported['features'][0]['geometry'], exported['features'][1]['geometry'])
        source = collected['geometries'][0]['value']
        # 来源是 EPSG:4326 的纬经顺序，原始坐标不得被就地重排。
        self.assertEqual(source['exterior'][0]['raw'], '31 121')
        self.assertEqual(source['exterior'][0]['values'], [31.0, 121.0])
        self.assertEqual(exported['features'][0]['geometry']['coordinates'][0][0], [121.0, 31.0])

    def test_back_reference_to_earlier_object(self):
        raw = samples()['sample.xml']
        collected = collect_bytes(raw)
        self.assertEqual([item['status'] for item in collected['features']], ['go', 'go'])
        self.assertEqual(collected['features'][0]['reference'], '#p1')
        self.assertEqual(collected['features'][0]['geometry_ref'],
                         collected['features'][1]['geometry_ref'])

    def test_missing_reference_blocks_feature_not_page_silently(self):
        collected = collect_bytes(samples()['dangling.xml'])
        self.assertEqual(collected['features'][0]['status'], 'blocked')
        self.assertEqual(collected['features'][0]['reason']['code'], 'unresolved-reference')
        self.assertFalse(collected['page']['complete'])
        self.assertIn('unresolved-reference',
                      [reason['code'] for reason in collected['page']['reasons']])

    def test_external_reference_is_not_fetched(self):
        raw = collection('<wfs:member><a:Area gml:id="x"><a:shape '
                         'xlink:href="https://example.invalid/geom"/></a:Area></wfs:member>')
        collected = collect_bytes(raw)
        self.assertEqual(collected['features'][0]['reason']['code'], 'external-reference')
        self.assertFalse(collected['page']['complete'])

    def test_conflicting_duplicate_id_blocks_both_occurrences(self):
        collected = collect_bytes(samples()['duplicate.xml'])
        statuses = [(item['id'], item['status']) for item in collected['features']]
        self.assertEqual(statuses, [('a1', 'blocked'), ('a2', 'go'), ('a1', 'blocked')])
        self.assertEqual(collected['features'][0]['reason']['code'], 'duplicate-reference')
        self.assertFalse(collected['page']['complete'])

    def test_identical_duplicate_id_is_reusable(self):
        point = ('<gml:Point gml:id="p" srsName="%s"><gml:pos>1 2</gml:pos></gml:Point>'
                 % CRS84)
        raw = collection(point + point + '<wfs:member><a:Area gml:id="x">'
                         '<a:shape xlink:href="#p"/></a:Area></wfs:member>')
        collected = collect_bytes(raw)
        self.assertEqual(collected['features'][0]['status'], 'go')


class PageCompletenessTests(unittest.TestCase):
    def test_number_matched_unknown_does_not_finish_pagination(self):
        collected = collect_bytes(samples()['sample.xml'])
        self.assertEqual(collected['page']['number_matched'], 'unknown')
        self.assertEqual(collected['page']['number_returned'], '2')
        self.assertEqual(collected['page']['collected'], 2)
        # 只要本页自身完整就是完整；不能因 numberMatched 未知而推断还有/没有下一页。
        self.assertTrue(collected['page']['complete'])

    def test_next_link_is_reported_not_followed(self):
        raw = collection(feature('x', '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos>'
                                      '</gml:Point>' % CRS84),
                         numberMatched='unknown', numberReturned='1',
                         next='https://example.invalid/page=2')
        collected = collect_bytes(raw)
        self.assertEqual(collected['page']['next'], 'https://example.invalid/page=2')
        self.assertEqual(collected['page']['collected'], 1)

    def test_pagination_follows_next_while_number_matched_unknown(self):
        routes = scenario()
        visited = []

        def fetch_page(url):
            visited.append(url.rsplit('/', 1)[-1])
            return fetch(url)

        with ReplaySource(routes) as server:
            result = collect_pages(fetch_page, server.url + '/pages/page-1')
        self.assertEqual(visited, ['page-1', 'page-2', 'page-3'])
        self.assertEqual(result['requests'], 3)
        self.assertIsNone(result['stopped'])
        self.assertEqual(result['number_matched'], ['unknown', 'unknown', 'unknown'])
        ids = [feature['id']
               for page in result['pages']
               for feature in page['geojson']['features']]
        self.assertEqual(ids, ['p1', 'p2', 'p3'])
        longitudes = [page['geojson']['features'][0]['geometry']['coordinates'][0]
                      for page in result['pages']]
        self.assertEqual(longitudes, [121.1, 121.2, 121.3])

    def test_pagination_stops_on_incomplete_page(self):
        routes = scenario()
        routes['GET /pages/page-2'] = [dict(routes['GET /pages/page-2'][0],
                                            disconnect_after=100)]
        with ReplaySource(routes) as server:
            result = collect_pages(fetch, server.url + '/pages/page-1')
        self.assertEqual(result['stopped']['code'], 'incomplete-page')
        self.assertEqual(len(result['pages']), 2)
        self.assertFalse(result['pages'][1]['collection']['page']['complete'])
        self.assertEqual(result['pages'][1]['geojson']['converted'], 0)

    def test_pagination_stops_on_cycle_and_limit(self):
        first = collection(feature('a', '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos>'
                                       '</gml:Point>' % CRS84), next='/loop')
        loop = collection(feature('b', '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos>'
                                      '</gml:Point>' % CRS84), next='/loop')
        route = lambda raw: [dict(base64=base64.b64encode(raw).decode())]
        with ReplaySource({'GET /loop': route(loop),
                           'GET /start': route(first)}) as server:
            result = collect_pages(fetch, server.url + '/start')
            self.assertEqual(result['stopped']['code'], 'pagination-cycle')
            self.assertEqual(len(result['pages']), 2)
            self.assertEqual(fetch(server.url + '/loop')[0], 200)
        with ReplaySource({'GET /loop': route(loop),
                           'GET /start': route(first)}) as server:
            limited = collect_pages(fetch, server.url + '/start', max_pages=1)
        self.assertEqual(limited['stopped']['code'], 'page-limit')

    def test_truncated_response_is_not_a_complete_page(self):
        raw = samples()['forward.xml']
        cut = raw[:raw.rindex(b'</gml:Polygon>')]
        collected = collect_bytes(cut, truncated=True)
        self.assertFalse(collected['page']['complete'])
        codes = [reason['code'] for reason in collected['page']['reasons']]
        self.assertIn('truncated', codes)
        self.assertTrue(all(item['status'] == 'blocked' for item in collected['features']))

    def test_every_collected_feature_points_back_to_source_node(self):
        raw = samples()['hole.xml']
        collected = collect_bytes(raw)
        source = collected['features'][0]['source']
        self.assertEqual(source['id'], 'z1')
        self.assertEqual(raw[source['start_byte']:source['start_byte']+20],
                         b'<a:Zone gml:id="z1">')
        self.assertEqual(source['start_line'], 1)
        geometry_source = collected['geometries'][0]['source']
        self.assertTrue(raw[geometry_source['start_byte']:].startswith(b'<gml:Polygon'))


class CollectionOverHttpTests(unittest.TestCase):
    def test_chunked_streaming_collection_matches_direct_parse(self):
        fixtures = samples()
        routes = {'GET /f': [dict(base64=base64.b64encode(fixtures['forward.xml']).decode(),
                                  chunk_bytes=1)]}
        with ReplaySource(routes) as server:
            status, headers, raw, complete = fetch(server.url + '/f')
        self.assertTrue(complete)
        self.assertEqual(collect_bytes(raw), collect_bytes(fixtures['forward.xml']))

    def test_disconnected_page_is_marked_incomplete(self):
        routes = scenario()
        with ReplaySource({'GET /t': routes['GET /features-truncated']}) as server:
            status, headers, raw, complete = fetch(server.url + '/t')
        self.assertEqual(status, 200)
        self.assertFalse(complete)
        collected = collect_bytes(raw, truncated=not complete)
        self.assertFalse(collected['page']['complete'])
        exported = export_bytes(raw, truncated=not complete)
        self.assertEqual(exported['converted'], 0)
        self.assertTrue(all(feature['geometry'] is None for feature in exported['features']))


class ArchiveTests(unittest.TestCase):
    def test_geometry_identity_and_page_state_are_stored(self):
        raw = samples()['forward.xml']
        collected = collect_bytes(raw)
        with tempfile.TemporaryDirectory() as directory:
            with Archive(Path(directory)/'store.sqlite3') as archive:
                first = archive.save('partner', raw, collected['features'], collected)
                again = archive.save('partner', raw, collected['features'], collected)
                self.assertEqual(first, again)
                rows = archive.geometries(first)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['gml_id'], 'shared')
                self.assertEqual(rows[0]['used_by'], ['f1', 'f2'])
                self.assertEqual(rows[0]['axis_order'], ['lat', 'lon'])
                self.assertEqual(archive.pages()[0]['complete'], True)
            with Archive(Path(directory)/'store.sqlite3') as archive:
                self.assertEqual(len(archive.list()), 1)
                self.assertEqual(archive.raw(first), raw)


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        import app, contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = app.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_export_and_locate_from_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'forward.xml'
            path.write_bytes(samples()['forward.xml'])
            code, out, err = self.run_cli(['export', str(path)])
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertEqual(report['converted'], 2)
            code, out, err = self.run_cli(['locate', str(path), '--id', 'shared',
                                           '--form', 'fragment'])
            self.assertEqual(code, 0, err)
            located = json.loads(out)
            self.assertEqual(located['text'], '<gml:Polygon gml:id="shared" srsName="urn:ogc:def:crs:EPSG::4326">')
            self.assertEqual(located['occurrences'], 1)
            self.assertIsNotNone(located['start_byte'])


class RobustnessTests(unittest.TestCase):
    def test_invalid_encoding_is_not_silently_accepted(self):
        raw = collection(feature('x', '<gml:Point srsName="%s"><gml:pos>31 121</gml:pos>'
                                      '</gml:Point>' % CRS84))
        broken = raw.replace(b'121', b'\xff1')
        collected = collect_bytes(broken)
        self.assertTrue(collected['source']['truncated'])
        self.assertIsNotNone(collected['source']['error'])
        self.assertFalse(collected['page']['complete'])
        self.assertEqual(export_bytes(broken)['converted'], 0)

    def test_external_entity_is_not_resolved_and_marks_page(self):
        raw = (b'<!DOCTYPE r [<!ENTITY ext SYSTEM "file:///etc/passwd">]>'
               + collection(feature('x', '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos>'
                                         '</gml:Point>' % CRS84)).replace(
                   b'<a:Area gml:id="x">', b'<a:Area gml:id="x"><a:n>&ext;</a:n>'))
        collected = collect_bytes(raw)
        self.assertEqual(collected['page']['complete'], False)
        self.assertIn('unresolved-entity',
                      [reason['code'] for reason in collected['page']['reasons']])

    def test_deep_nesting_is_blocked_not_crashing(self):
        body = '<gml:Point srsName="%s"><gml:pos>1 2</gml:pos></gml:Point>' % CRS84
        for _ in range(200):
            body = ('<gml:MultiGeometry srsName="%s"><gml:geometryMember>%s'
                    '</gml:geometryMember></gml:MultiGeometry>') % (CRS84, body)
        raw = collection('<wfs:member><a:Area gml:id="x"><a:shape>%s</a:shape>'
                         '</a:Area></wfs:member>' % body)
        collected = collect_bytes(raw)
        self.assertEqual(collected['features'][0]['reason']['code'], 'nesting-too-deep')

    def test_gml31_namespace_is_not_interpreted_as_gml32(self):
        raw = ('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
               ' xmlns:g="http://www.opengis.net/gml" xmlns:a="urn:areas">'
               '<wfs:member><a:Area gml:id="x"><a:shape>'
               '<g:Point srsName="%s"><g:pos>31 121</g:pos></g:Point>'
               '</a:shape></a:Area></wfs:member></wfs:FeatureCollection>') % CRS84
        raw = raw.replace('gml:id', 'g:id').replace('xmlns:a', 'xmlns:a')
        exported = export_bytes(raw.encode())
        self.assertEqual(exported['features'][0]['reason']['code'], 'unsupported-namespace')

    def test_legacy_identifier_table_rows_are_features(self):
        raw = ('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
               ' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
               ' xmlns:xlink="http://www.w3.org/1999/xlink">'
               '<a:Areas id="1"><a:shape xlink:href="#id:1"/><a:name>alpha</a:name></a:Areas>'
               '<a:Areas id="2"><a:shape xlink:href="#id:2"/><a:name>beta</a:name></a:Areas>'
               '<gml:Point gml:id="1" srsName="%s"><gml:pos>121 31</gml:pos></gml:Point>'
               '<gml:Point gml:id="2" srsName="%s"><gml:pos>122 32</gml:pos></gml:Point>'
               '</wfs:FeatureCollection>') % (CRS84, CRS84)
        exported = export_bytes(raw.encode())
        self.assertEqual([feature['properties']['properties']['name']
                          for feature in exported['features']], ['alpha', 'beta'])
        self.assertEqual([feature['geometry']['coordinates']
                          for feature in exported['features']],
                         [[121.0, 31.0], [122.0, 32.0]])
        self.assertEqual(exported['features'][0]['properties']['properties']['reference'],
                         '#id:1')

    def test_non_wfs_root_is_rejected(self):
        with self.assertRaises(ValueError):
            collect_bytes(b'<FeatureCollection/>')


if __name__ == '__main__':
    unittest.main()

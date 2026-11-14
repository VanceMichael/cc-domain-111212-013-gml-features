HEAD = (b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
        b' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
        b' xmlns:xlink="http://www.w3.org/1999/xlink" numberMatched="unknown" numberReturned="2">')

SAMPLE = HEAD + (
    b'<wfs:member><a:Area gml:id="a1"><a:shape xlink:href="#p1"/></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="a2"><a:shape><gml:Point gml:id="p1" srsName="urn:ogc:def:crs:EPSG::4326">'
    b'<gml:pos>31 121</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'</wfs:FeatureCollection>')

CRS84 = SAMPLE.replace(b'urn:ogc:def:crs:EPSG::4326', b'urn:ogc:def:crs:OGC:1.3:CRS84').replace(b'31 121', b'121 31')

D3 = HEAD + (
    b'<wfs:member><a:Area gml:id="east"><a:shape><gml:Point srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="3">'
    b'<gml:pos>31.50 120.25 12.5</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="pole"><a:shape><gml:Point srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="3">'
    b'<gml:pos>89.9 0.0 800</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'</wfs:FeatureCollection>')

HOLES = HEAD + (
    b'<wfs:member><a:Zone gml:id="z1"><a:shape>'
    b'<gml:Polygon gml:id="poly-1" srsName="urn:ogc:def:crs:OGC:1.3:CRS84" srsDimension="2">'
    b'<gml:exterior><gml:LinearRing><gml:posList>121 31 121.05 31 121.05 31.05 121 31.05 121 31</gml:posList></gml:LinearRing></gml:exterior>'
    b'<gml:interior><gml:LinearRing><gml:posList>121.01 31.01 121.02 31.01 121.02 31.02 121.01 31.02 121.01 31.01</gml:posList></gml:LinearRing></gml:interior>'
    b'<gml:interior><gml:LinearRing><gml:posList>121.03 31.03 121.04 31.03 121.04 31.04 121.03 31.04 121.03 31.03</gml:posList></gml:LinearRing></gml:interior>'
    b'</gml:Polygon></a:shape></a:Zone></wfs:member>'
    b'</wfs:FeatureCollection>')

GEOMETRIES = HEAD + (
    b'<gml:Point gml:id="pt-a" srsName="urn:ogc:def:crs:OGC:1.3:CRS84"><gml:pos>120.5 30.5</gml:pos></gml:Point>'
    b'<wfs:member><a:Area gml:id="area-l"><a:shape>'
    b'<gml:LineString srsName="urn:ogc:def:crs:OGC:1.3:CRS84"><gml:posList>120.1 30.1 120.2 30.2 120.3 30.3</gml:posList></gml:LineString>'
    b'</a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="area-c"><a:shape>'
    b'<gml:Curve srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:segments><gml:LineStringSegment><gml:posList>120.4 30.4 120.5 30.5 120.6 30.4</gml:posList></gml:LineStringSegment></gml:segments>'
    b'</gml:Curve></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="area-m"><a:shape>'
    b'<gml:MultiGeometry srsName="urn:ogc:def:crs:OGC:1.3:CRS84" srsDimension="2">'
    b'<gml:geometryMember xlink:href="#pt-a"/>'
    b'<gml:geometryMember><gml:Point><gml:pos>120.7 30.7</gml:pos></gml:Point></gml:geometryMember>'
    b'</gml:MultiGeometry></a:shape></a:Area></wfs:member>'
    b'</wfs:FeatureCollection>')

FORWARD = (b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
           b' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
           b' xmlns:xlink="http://www.w3.org/1999/xlink" numberMatched="unknown" numberReturned="2">'
           b'<wfs:member><a:Area gml:id="f1"><a:shape xlink:href="#shared"/></a:Area></wfs:member>'
           b'<wfs:member><a:Area gml:id="f2"><a:shape xlink:href="#shared"/></a:Area></wfs:member>'
           b'<a:Areas>'
           b'<gml:Polygon gml:id="shared" srsName="urn:ogc:def:crs:EPSG::4326">'
           b'<gml:exterior><gml:LinearRing><gml:posList>31 121 31 121.02 31.02 121.02 31.02 121 31 121</gml:posList></gml:LinearRing></gml:exterior>'
           b'<gml:interior><gml:LinearRing><gml:posList>31.005 121.005 31.005 121.015 31.015 121.015 31.015 121.005 31.005 121.005</gml:posList></gml:LinearRing></gml:interior>'
           b'</gml:Polygon>'
           b'</a:Areas></wfs:FeatureCollection>')

# Derived only by byte-preserving edits of the fixtures above.
BROKEN = HEAD + (
    b'<wfs:member><a:Area gml:id="arc"><a:shape>'
    b'<gml:Curve srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:segments><gml:Arc><gml:posList>120.2 30.2 120.3 30.3 120.4 30.2</gml:posList></gml:Arc></gml:segments>'
    b'</gml:Curve></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Zone gml:id="bad-dim"><a:shape>'
    b'<gml:Polygon srsName="urn:ogc:def:crs:OGC:1.3:CRS84" srsDimension="3">'
    b'<gml:exterior><gml:LinearRing><gml:posList>121 31 121.05 31 121.05 31.05 121 31.05 121 31</gml:posList></gml:LinearRing></gml:exterior>'
    b'</gml:Polygon></a:shape></a:Zone></wfs:member>'
    b'<wfs:member><a:Zone gml:id="bad-closed"><a:shape>'
    b'<gml:Polygon srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:exterior><gml:LinearRing><gml:posList>121 31 121.05 31 121.05 31.05 121 31.05</gml:posList></gml:LinearRing></gml:exterior>'
    b'</gml:Polygon></a:shape></a:Zone></wfs:member>'
    b'<wfs:member><a:Area gml:id="bad-parent"><a:shape>'
    b'<gml:MultiGeometry srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:geometryMember><gml:Point><gml:pos>120.8 30.8</gml:pos></gml:Point></gml:geometryMember>'
    b'<gml:geometryMember><gml:Point srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>30.9 120.9</gml:pos></gml:Point></gml:geometryMember>'
    b'</gml:MultiGeometry></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="bad-ref"><a:shape xlink:href="#missing"/></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="bad-value"><a:shape><gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:pos>121 east</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'</wfs:FeatureCollection>')

# Three members where gml:id="a1" is declared twice with conflicting content.
DUPLICATE = HEAD + (
    b'<wfs:member><a:Area gml:id="a1"><a:shape><gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:pos>20 110</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="a2"><a:shape><gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:pos>20.5 110.5</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'<wfs:member><a:Area gml:id="a1"><a:shape><gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
    b'<gml:pos>21 111</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
    b'</wfs:FeatureCollection>')

# Forward reference whose target never appears in the document.
DANGLING = (b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
            b' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
            b' xmlns:xlink="http://www.w3.org/1999/xlink" numberMatched="1" numberReturned="1">'
            b'<wfs:member><a:Area gml:id="lonely"><a:shape xlink:href="#nowhere"/></a:Area></wfs:member>'
            b'</wfs:FeatureCollection>')

# Sources whose axis order cannot be proven: an unregistered projected CRS, a
# commonly seen but unregistered short form, and a missing srsName.
UNKNOWN = (b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
           b' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
           b' numberMatched="unknown" numberReturned="3">'
           b'<wfs:member><a:Area gml:id="web-mercator"><a:shape>'
           b'<gml:Point srsName="urn:ogc:def:crs:EPSG::3857"><gml:pos>13465233 3642037</gml:pos></gml:Point>'
           b'</a:shape></a:Area></wfs:member>'
           b'<wfs:member><a:Area gml:id="short-form"><a:shape>'
           b'<gml:Point srsName="EPSG:4326"><gml:pos>31 121</gml:pos></gml:Point>'
           b'</a:shape></a:Area></wfs:member>'
           b'<wfs:member><a:Area gml:id="no-srs"><a:shape>'
           b'<gml:Point><gml:pos>31 121</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
           b'</wfs:FeatureCollection>')

def _page(name, feature_id, following, longitude):
    anchor = ' next="%s"' % following if following else ''
    return (('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"'
             ' xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas"'
             ' numberMatched="unknown" numberReturned="1"%s>'
             '<wfs:member><a:Area gml:id="%s"><a:shape>'
             '<gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
             '<gml:pos>%s 31</gml:pos></gml:Point></a:shape></a:Area></wfs:member>'
             '</wfs:FeatureCollection>') % (anchor, feature_id, longitude)).encode()


# numberMatched 始终未知，但 next 明确指向下一页：采集必须按 next 继续。
PAGES = [
    ('page-1', _page('page-1', 'p1', 'page-2', '121.1')),
    ('page-2', _page('page-2', 'p2', 'page-3', '121.2')),
    ('page-3', _page('page-3', 'p3', None, '121.3')),
]

def samples():
    return {
        'sample.xml': SAMPLE,
        'crs84.xml': CRS84,
        'dim3.xml': D3,
        'hole.xml': HOLES,
        'geometry.xml': GEOMETRIES,
        'forward.xml': FORWARD,
        'broken.xml': BROKEN,
        'unknown.xml': UNKNOWN,
        'duplicate.xml': DUPLICATE,
        'dangling.xml': DANGLING,
        'invalid.xml': b'<FeatureCollection/>',
    }

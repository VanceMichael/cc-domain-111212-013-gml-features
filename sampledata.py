def samples():
    collection = b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:a="urn:areas" xmlns:xlink="http://www.w3.org/1999/xlink" numberMatched="unknown" numberReturned="2"><wfs:member><a:Area gml:id="a1"><a:shape xlink:href="#p1"/></a:Area></wfs:member><wfs:member><a:Area gml:id="a2"><a:shape><gml:Point gml:id="p1" srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>31 121</gml:pos></gml:Point></a:shape></a:Area></wfs:member></wfs:FeatureCollection>'
    return {'sample.xml': collection,
            'crs84.xml': collection.replace(b'urn:ogc:def:crs:EPSG::4326', b'urn:ogc:def:crs:OGC:1.3:CRS84').replace(b'31 121', b'121 31'),
            'invalid.xml': b'<FeatureCollection/>'}

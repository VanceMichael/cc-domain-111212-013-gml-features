import xml.etree.ElementTree as ET

def inspect_bytes(data):
    root = ET.fromstring(data)
    namespace = '{http://www.opengis.net/gml/3.2}'
    if root.tag != '{http://www.opengis.net/wfs/2.0}FeatureCollection':
        raise ValueError('不是 WFS 2.0 要素集合')
    result = []
    for node in root.iter():
        identity = node.get(namespace + 'id')
        if identity:
            result.append({'id': identity, 'tag': node.tag, 'srs': node.get('srsName')})
    return result

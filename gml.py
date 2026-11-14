"""WFS/GML 响应文档模型。

用流式 expat 建树，同时保留每个元素的原始字节区间、gml:id/xml:id 索引和引用
锚点。这样做的目的：

* 引用（xlink:href="#id"）只能解析到同一响应中真实存在的对象，且能区分“目标
  尚未出现”“目标未闭合”“目标重复声明且内容冲突”。
* 收集失败时能回到响应中的具体节点（字节、行、列与原文切片）。
* 响应从中途截断时，已闭合节点仍然可用，但文档整体标记为不完整。
"""

import bisect
from xml.parsers import expat

GML = 'http://www.opengis.net/gml/3.2'
GML_LEGACY = 'http://www.opengis.net/gml'
WFS = 'http://www.opengis.net/wfs/2.0'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
XLINK = 'http://www.w3.org/1999/xlink'
SEP = '\x1f'

XLINK_HREF = XLINK + SEP + 'href'
XLINK_TYPE = XLINK + SEP + 'type'
GML_ID = GML + SEP + 'id'
XML_ID = XML_NS + SEP + 'id'
GML_LEGACY_ID = GML_LEGACY + SEP + 'id'

WFS_MEMBER = WFS + SEP + 'member'
GML_FEATURE_MEMBER = GML + SEP + 'featureMember'
GML_FEATURE_MEMBERS = GML + SEP + 'featureMembers'
MEMBER_CONTAINERS = {WFS_MEMBER, GML_FEATURE_MEMBER, GML_FEATURE_MEMBERS}
FEATURE_COLLECTION = WFS + SEP + 'FeatureCollection'

GEOMETRY_LOCAL = {
    'Point', 'LineString', 'LinearRing', 'Ring', 'Curve', 'Polygon', 'Surface',
    'MultiGeometry', 'MultiPoint', 'MultiCurve', 'MultiSurface', 'MultiLineString',
    'MultiPolygon', 'PolygonPatch', 'Rectangle', 'Tin', 'TriangulatedSurface',
    'Solid', 'CompositeSurface', 'CompositeCurve', 'CompositePoint',
}


def local_name(qualified):
    return qualified.split(SEP)[-1]


def namespace_of(qualified):
    return qualified.rsplit(SEP, 1)[0] if SEP in qualified else ''


def display_tag(qualified):
    """把 expat 的命名空间名还原为 {uri}local 形式，便于与 XML 原文对照。"""
    if SEP in qualified:
        namespace, name = qualified.rsplit(SEP, 1)
        return '{' + namespace + '}' + name if namespace else name
    return qualified


def is_geometry_tag(qualified):
    return namespace_of(qualified) == GML and local_name(qualified) in GEOMETRY_LOCAL


def is_legacy_geometry_tag(qualified):
    """GML 3.1 命名空间的几何：词汇相近但坐标系约定不同，不能按 3.2 解释。"""
    return namespace_of(qualified) == GML_LEGACY and local_name(qualified) in GEOMETRY_LOCAL


class Node:
    """一个解析到的元素。未闭合节点（响应被截断）的 end 为 None。"""

    __slots__ = ('tag', 'attrs', 'id', 'gml_id', 'plain_id', 'start', 'end',
                 'open_end', 'self_closing', 'parent', 'children', 'text_parts',
                 'text', 'closed', 'feature', 'member_index', 'kind')

    def __init__(self, tag, attrs, start, parent, open_end, self_closing):
        self.tag = tag
        self.attrs = attrs
        self.id = ''
        self.gml_id = ''
        self.plain_id = ''
        self.start = start
        self.end = None
        self.open_end = open_end
        self.self_closing = self_closing
        self.parent = parent
        self.children = []
        self.text_parts = []
        self.text = ''
        self.closed = False
        self.feature = False
        self.member_index = None
        self.kind = None

    @property
    def local(self):
        return local_name(self.tag)

    @property
    def source(self):
        """回到响应节点所需的最小定位信息。"""
        return dict(id=self.id or None, tag=display_tag(self.tag),
                    start_byte=self.start, end_byte=self.end, closed=self.closed)

    @property
    def raw_span_known(self):
        return self.end is not None

    def __repr__(self):
        return '<Node %s id=%r bytes=%s-%s>' % (
            display_tag(self.tag), self.id or None, self.start, self.end)


class Document:
    def __init__(self, raw, truncated=False):
        self.raw = raw
        self.truncated = bool(truncated)
        self.root = None
        self.nodes = []                 # 起始顺序
        self.ids = {}                   # gml:id/xml:id -> [Node]
        self.plain_ids = {}             # 无命名空间 id -> [Node]
        self.anchors = {}               # '#fragment' -> [Node]
        self.features = []
        self.member_counter = 0
        self.stack = []
        self.open_nodes = []
        self.entity_references = []
        self.close_error = None
        self._newlines = [index for index, byte in enumerate(raw) if byte == 10]

    # ---- 解析 -------------------------------------------------------------
    @classmethod
    def parse(cls, raw, truncated=False):
        if isinstance(raw, str):
            raw = raw.encode('utf8')
        document = cls(raw, truncated=truncated)
        try:
            document._parse()
        except expat.ExpatError as error:
            document.close_error = error
            document.truncated = True
        document._close_open_nodes()
        document._classify_features()
        return document

    def _parse(self):
        parser = expat.ParserCreate(namespace_separator=SEP)
        parser.buffer_text = True

        def start(tag, attrs):
            start_byte = parser.CurrentByteIndex
            tag_end, self_closing = _scan_start_tag(self.raw, start_byte)
            parent = self.stack[-1] if self.stack else None
            node = Node(tag, attrs, start_byte, parent, tag_end, self_closing)
            if parent is not None:
                parent.children.append(node)
            else:
                self.root = node
            self._index(node)
            if parent is not None and parent.tag in MEMBER_CONTAINERS:
                behaves_as_feature = not is_geometry_tag(node.tag)
                if behaves_as_feature:
                    node.feature = True
                    node.member_index = self.member_counter
                    self.member_counter += 1
                    self.features.append(node)
            self.stack.append(node)
            self.nodes.append(node)

        def end(tag):
            node = self.stack.pop()
            if node.self_closing:
                node.end = node.open_end
                node.closed = True
            elif parser.CurrentByteIndex is not None:
                close = self.raw.find(b'>', parser.CurrentByteIndex)
                node.end = close + 1 if close >= 0 else None
                node.closed = node.end is not None
            node.text = ''.join(node.text_parts)
            node.text_parts = []

        def characters(text):
            if self.stack:
                self.stack[-1].text_parts.append(text)

        def skipped_entity(name, is_parameter):
            # 未解析的实体引用会让文本悄悄缺一段，必须记下来，不能当成完整属性值。
            self.entity_references.append(name)

        def external_entity(context, base, system_id, public_id):
            # 不打开外部实体（文件、网络都不读），只登记后按“已处理但为空”继续。
            # expat 带命名空间分隔符时把上下文写成 "<prefix=uri>\x0c<name>"。
            name = None
            if context:
                name = context.rsplit('\x0c', 1)[-1]
                if name == context:
                    name = name.rsplit('=', 1)[-1]
            self.entity_references.append(name or system_id or public_id or '?')
            return 1

        parser.StartElementHandler = start
        parser.EndElementHandler = end
        parser.CharacterDataHandler = characters
        parser.SkippedEntityHandler = skipped_entity
        parser.ExternalEntityRefHandler = external_entity
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        try:
            parser.Parse(self.raw, True)
        finally:
            if self.stack:
                # 截断：仍把已收到的文本归到最后一个未闭合节点。
                for node in self.stack:
                    node.text = ''.join(node.text_parts)

    def _index(self, node):
        identity = node.attrs.get(GML_ID) or node.attrs.get(GML_LEGACY_ID)
        gml_identity = bool(identity)
        if not identity:
            identity = node.attrs.get(XML_ID)
        if identity:
            node.id = identity
            if gml_identity:
                node.gml_id = identity
            self.ids.setdefault(identity, []).append(node)
            self.anchors.setdefault('#' + identity, []).append(node)
        plain = node.attrs.get('id')
        if plain:
            node.plain_id = plain
            self.plain_ids.setdefault(plain, []).append(node)
            self.anchors.setdefault('#' + plain, []).append(node)
        # GML 3.2 允许使用普通 id 属性；WFS 旧式标识表也用它。两者都参与引用查找。

    def _close_open_nodes(self):
        for node in self.stack:
            node.text = ''.join(node.text_parts)
            node.closed = False
        self.open_nodes = list(self.stack)

    def _classify_features(self):
        if self.features:
            return
        # 没有标准成员容器时的兼容路径：集合根下带标识的业务元素视为要素。
        if self.root is None:
            return
        for child in self.root.children:
            if (child.id or child.plain_id) and namespace_of(child.tag) not in (GML, WFS):
                child.feature = True
                child.member_index = self.member_counter
                self.member_counter += 1
                self.features.append(child)

    # ---- 查询 -------------------------------------------------------------
    def find(self, href):
        """解析同源响应内的 #fragment 引用。只做索引查找，不发起任何外部请求。"""
        if not href.startswith('#'):
            raise ReferenceError('external-reference', '不是同源文档片段引用：' + href)
        target = href[1:]
        if not target:
            raise ReferenceError('unresolved-reference', '空引用')
        matches = self.anchors.get(href)
        if not matches:
            matches = self.ids.get(target)
        if not matches and ':' in target:
            # 旧式标识表写作 #id:<n>：优先指向 gml:id，其次才是无命名空间 id。
            prefix, identifier = target.split(':', 1)
            matches = self.ids.get(identifier) or self.plain_ids.get(identifier)
        if not matches:
            raise ReferenceError('unresolved-reference', '响应中不存在引用目标：' + href)
        return matches

    def content(self, node, limit=None):
        end = node.end if node.end is not None else len(self.raw)
        return self.raw[node.start:end]

    def identity_state(self, identifier, occurrence=0):
        """同 id 多次声明时，只有原文完全一致才可复用。"""
        matches = self.ids.get(identifier)
        if not matches:
            return 'missing'
        if len(matches) == 1:
            return 'unique'
        spans = {self.content(node) for node in matches}
        return 'identical' if len(spans) == 1 else 'conflict'

    def position(self, offset):
        """行号从 1 开始；列按字符计（不是字节），便于与编辑器/原文对照。"""
        index = bisect.bisect_left(self._newlines, offset)
        line = index + 1
        line_start = self._newlines[index - 1] + 1 if index else 0
        column = len(self.raw[line_start:offset].decode('utf8', 'replace'))
        return line, column

    def locate(self, identifier, occurrence=0, form='xml'):
        matches = self.ids.get(identifier)
        if not matches:
            raise KeyError(identifier)
        if occurrence < 0 or occurrence >= len(matches):
            raise KeyError(identifier)
        node = matches[occurrence]
        end = node.end if node.end is not None else len(self.raw)
        line, column = self.position(node.start)
        report = dict(id=identifier, tag=display_tag(node.tag),
                      start_byte=node.start, end_byte=end,
                      start_line=line, start_column=column,
                      closed=node.closed, occurrence=occurrence,
                      occurrences=len(matches))
        if form in ('xml', 'text'):
            report['text'] = self.raw[node.start:end].decode('utf8', 'replace')
        if form == 'fragment':
            opening_end = self.raw.find(b'>', node.start)
            opening_end = opening_end + 1 if opening_end >= 0 else end
            report['text'] = self.raw[node.start:opening_end].decode('utf8', 'replace')
        return report


class ReferenceError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _scan_start_tag(raw, start):
    """返回起始标签的结束位置与是否自闭合，能正确处理属性值中的引号和 '>'。"""
    index = start + 1
    quote = 0
    size = len(raw)
    while index < size:
        byte = raw[index]
        if quote:
            if byte == quote:
                quote = 0
        elif byte in (0x22, 0x27):
            quote = byte
        elif byte == 0x3E:
            return index + 1, raw[start:index].rstrip().endswith(b'/')
        index += 1
    return None, False

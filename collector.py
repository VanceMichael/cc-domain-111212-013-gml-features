"""按来源声明解释 GML 要素与几何，并导出坐标语义明确的 GeoJSON。

原则：

* 轴顺序与维度只看来源声明的 srsName / srsDimension；未登记的 CRS 不猜、不换算。
* 引用只解析同一响应内出现的对象，前向引用在整页收完后统一解析；同一对象被多个
  要素复用时保留同一个几何身份。
* 坐标保留来源顺序与原始数值，GeoJSON 输出时才按已证明的轴顺序重排为经、纬
  （以及可选的高程）。不能证明的来源不导出坐标，只给出原因与响应节点位置。
* 单个要素的坏几何与其他要素隔离；响应截断、引用未闭合则整页不算完整。
"""

from gml import (SEP, WFS, XLINK_HREF, ReferenceError, display_tag, is_geometry_tag,
                 is_legacy_geometry_tag, local_name)

# 已登记的 CRS：维度 -> 轴顺序。只登记能由标准文本直接证实的轴序。
# EPSG:4326 的 URN 形式是“纬度、经度”，CRS84 是“经度、纬度”；4326 的三维
# 形式第三轴为椭球高。未列出的 srsName（如 EPSG:3857、短写 EPSG:4326）不猜。
CRS = {
    'urn:ogc:def:crs:EPSG::4326': {2: ('lat', 'lon'), 3: ('lat', 'lon', 'h')},
    'urn:ogc:def:crs:EPSG:6.6:4326': {2: ('lat', 'lon'), 3: ('lat', 'lon', 'h')},
    'http://www.opengis.net/def/crs/EPSG/0/4326': {2: ('lat', 'lon'), 3: ('lat', 'lon', 'h')},
    'urn:ogc:def:crs:OGC:1.3:CRS84': {2: ('lon', 'lat')},
    'http://www.opengis.net/def/crs/OGC/1.3/CRS84': {2: ('lon', 'lat')},
}

MAX_DEPTH = 64


class FeatureBlocked(Exception):
    """单个要素内的几何/引用问题；只影响该要素。"""

    def __init__(self, code, detail, node=None, reference=None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.node = node
        self.reference = reference


class Collector:
    def __init__(self, document, crs=None, max_depth=MAX_DEPTH):
        self.document = document
        self.crs = dict(CRS)
        self.crs.update(crs or {})
        self.max_depth = max_depth
        self.cache = {}            # 节点起始字节 -> 几何引用编号
        self.geometries = []
        self.reference_targets = {}  # 引用编号 -> 源节点，供导出与回溯
        self._counter = 0

    # ---- 顶层 -------------------------------------------------------------
    def collect(self):
        if self.document.root is not None and self.document.root.tag != WFS + SEP + 'FeatureCollection':
            raise ValueError('不是 WFS 2.0 要素集合')
        features = [self._feature(node) for node in self.document.features]
        page = self._page(features)
        return dict(
            source=dict(truncated=self.document.truncated,
                        error=self._parse_error()),
            page=page,
            crs=dict(registered=sorted(self.crs), default=None,
                     note='只按登记条目解释轴序；未登记不猜测、不联网查表'),
            geometries=[dict(entry) for entry in self.geometries],
            features=features)

    def _parse_error(self):
        error = self.document.close_error
        if error is None:
            return None
        from xml.parsers import expat
        return dict(code=error.code, line=error.lineno, column=error.offset,
                    reason=expat.errors.messages.get(error.code, str(error)))

    def _next_link(self):
        """WFS 2.0 的下一页链接在 wfs:FeatureCollection 上，可能是 next 属性，
        也可能是 xlink:href 子元素；两种形式都原样报告。"""
        root = self.document.root
        if root is None:
            return None
        value = root.attrs.get('next')
        if value:
            return value
        for child in root.children:
            if local_name(child.tag) == 'next':
                if is_geometry_tag(child.tag):
                    continue
                return (child.attrs.get(XLINK_HREF) or child.text or '').strip() or None
        return None

    def _page(self, features):
        reasons = []
        if self.document.truncated:
            reasons.append(dict(code='truncated',
                                detail='响应未正常结束，已收下的内容不等于完整一页'))
        open_nodes = getattr(self.document, 'open_nodes', [])
        if open_nodes:
            reasons.append(dict(code='unclosed-elements',
                                tags=[display_tag(node.tag) for node in open_nodes],
                                detail='存在未闭合元素，引用闭包和要素边界无法判定'))
        if getattr(self.document, 'entity_references', None):
            reasons.append(dict(code='unresolved-entity',
                                names=sorted(set(self.document.entity_references)),
                                detail='响应引用了未解析的实体，文本可能不完整'))
        problems = {}
        for feature in features:
            for problem in feature.get('page_reasons', []):
                problems.setdefault(problem['code'], []).append(problem['reference'])
        for code in sorted(problems):
            references = sorted(set(problems[code]))
            reasons.append(dict(code=code, references=references,
                                detail='引用目标在本页中未闭合、缺失、外部或重复冲突'))
        return dict(complete=not reasons, reasons=reasons,
                    collected=sum(1 for item in features if item['status'] == 'go'),
                    blocked=sum(1 for item in features if item['status'] == 'blocked'),
                    number_matched=self._root_attr('numberMatched'),
                    number_returned=self._root_attr('numberReturned'),
                    next=self._next_link(),
                    note='完整性由截断与引用闭包判定；numberMatched 未知时既不用于提前结束，也不用于推断页数')

    def _root_attr(self, name):
        root = self.document.root
        return root.attrs.get(name) if root is not None else None

    # ---- 要素 -------------------------------------------------------------
    def _feature(self, node):
        report = dict(id=node.id or None, member_index=node.member_index,
                      tag=display_tag(node.tag), source=self._source(node),
                      status='go', reason=None, geometry_ref=None, crs=None,
                      properties=[], page_reasons=[], _reference_problems=[])
        try:
            if not node.closed:
                raise FeatureBlocked('unclosed-feature',
                                     '要素的闭合标签未收到，不能当作完整要素', node)
            if node.id and self.document.identity_state(node.id) == 'conflict':
                raise FeatureBlocked('duplicate-reference',
                                     'gml:id=%s 在响应中重复声明且内容冲突' % node.id,
                                     node, reference='#' + node.id)
            slots = self._slots(node)
            report['properties'] = self._properties(node, report['page_reasons'])
            if len(slots) > 1:
                raise FeatureBlocked('multiple-geometries',
                                     '一个要素下找到 %d 个几何，GeoJSON 要素只能承载一个'
                                     % len(slots))
            if slots:
                reference, href = self._slot(slots[0], node, report['_reference_problems'])
                report['geometry_ref'] = reference
                if href:
                    report['reference'] = href
                geometry = self._geometry(reference)
                report['crs'] = geometry['crs']
                label = report['id'] or 'member-%s' % report['member_index']
                if label not in geometry['used_by']:
                    geometry['used_by'].append(label)
                if report['crs']['status'] != 'verified':
                    raise FeatureBlocked(
                        report['crs']['status'] + '-crs',
                        report['crs']['detail'], slots[0])
        except FeatureBlocked as error:
            report['status'] = 'blocked'
            report['reason'] = self._reason(error)
            if error.reference:
                report['reference'] = error.reference
                if error.code in ('unresolved-reference', 'unclosed-reference',
                                  'duplicate-reference', 'external-reference'):
                    if not any(problem['reference'] == error.reference
                               for problem in report['_reference_problems']):
                        report['_reference_problems'].append(
                            dict(code=error.code, reference=error.reference))
        report['page_reasons'] = report['_reference_problems']
        del report['_reference_problems']
        return report

    def _reason(self, error):
        reason = dict(code=error.code, detail=error.detail)
        if error.reference is not None:
            reason['reference'] = error.reference
        if error.node is not None:
            reason['source'] = self._source(error.node)
        return reason

    def _source(self, node):
        line, column = self.document.position(node.start)
        return dict(tag=display_tag(node.tag), id=node.id or None,
                    start_byte=node.start, end_byte=node.end,
                    start_line=line, start_column=column, closed=node.closed)

    # ---- 定位几何属性 -----------------------------------------------------
    def _href_kind(self, node):
        """判定带 xlink:href 的叶子属性：同源几何 / 同源非几何 / 外部 / 未解析。"""
        href = node.attrs.get(XLINK_HREF)
        if not href.startswith('#'):
            return 'external'
        try:
            matches = self.document.find(href)
        except ReferenceError:
            return 'unresolved'
        target = matches[0]
        return 'geometry' if self._is_geometry(target) else 'property'

    def _is_geometry(self, node):
        return is_geometry_tag(node.tag) or is_legacy_geometry_tag(node.tag)

    def _slots(self, node):
        slots = []

        def walk(parent, depth):
            if depth > self.max_depth:
                raise FeatureBlocked('nesting-too-deep', '属性嵌套超过限制', parent)
            for child in parent.children:
                if self._is_geometry(child):
                    slots.append(child)
                    continue
                href = child.attrs.get(XLINK_HREF)
                if href and not child.children:
                    kind = self._href_kind(child)
                    if kind in ('geometry', 'unresolved', 'external'):
                        slots.append(child)
                    continue
                walk(child, depth + 1)

        walk(node, 0)
        return slots

    def _properties(self, node, page_reasons):
        properties = []
        for child in node.children:
            if self._is_geometry(child):
                continue
            href = child.attrs.get(XLINK_HREF)
            if href and not child.children:
                if self._href_kind(child) == 'geometry':
                    continue
            if self._contains_geometry(child):
                continue
            name = local_name(child.tag)
            value = self._property_value(child, 0, page_reasons, ())
            properties.append(dict(name=name, value=value))
        return properties

    def _contains_geometry(self, node):
        stack = list(node.children)
        if self._is_geometry(node):
            return True
        while stack:
            current = stack.pop()
            if self._is_geometry(current):
                return True
            href = current.attrs.get(XLINK_HREF)
            if href and not current.children and self._href_kind(current) == 'geometry':
                return True
            stack.extend(current.children)
        return False

    def _property_value(self, node, depth, page_reasons, stack):
        if depth > self.max_depth or node.start in stack:
            raise FeatureBlocked('nesting-too-deep', '属性嵌套超过限制或成环', node)
        stack = tuple(stack) + (node.start,)
        href = node.attrs.get(XLINK_HREF)
        if href:
            if self._href_kind(node) == 'external':
                page_reasons.append(dict(code='external-reference', reference=href))
                return dict(reference=href, resolved=False,
                            detail='外部引用不在同源响应内，未解析')
            try:
                target = self._reference(href, node, 'property')
            except FeatureBlocked as error:
                page_reasons.append(dict(code=error.code, reference=href))
                return dict(reference=href, resolved=False,
                            error=dict(code=error.code, detail=error.detail))
            return dict(reference=href, resolved_id=target.id or None,
                        resolved=True, value=target.text.strip() if target.text else None,
                        source=self._source(target))
        if node.children:
            return dict(children=[dict(name=local_name(child.tag),
                                       value=self._property_value(child, depth + 1,
                                                                  page_reasons, stack))
                                  for child in node.children],
                        text=node.text.strip() or None)
        return node.text.strip() or None

    # ---- 引用 -------------------------------------------------------------
    def _slot(self, slot, feature, problems):
        href = slot.attrs.get(XLINK_HREF)
        if href:
            try:
                target = self._reference(href, slot, 'geometry')
            except FeatureBlocked as error:
                if error.reference:
                    problems.append(dict(code=error.code, reference=error.reference))
                raise
            return self._decode(target, []), href
        return self._decode(slot, []), None

    def _reference(self, href, origin, purpose):
        if not href.startswith('#'):
            raise FeatureBlocked('external-reference',
                                 '只解析同源响应内的片段引用：' + href, origin,
                                 reference=href)
        try:
            matches = self.document.find(href)
        except ReferenceError as error:
            raise FeatureBlocked('unresolved-reference', error.detail, origin,
                                 reference=href) from None
        closed = [node for node in matches if node.closed]
        if len(closed) != len(matches):
            raise FeatureBlocked('unclosed-reference',
                                 '引用目标 %s 的闭合标签未收到' % href, origin,
                                 reference=href)
        if len(matches) > 1 and len({self.document.content(node) for node in matches}) > 1:
            raise FeatureBlocked('duplicate-reference',
                                 '引用目标 %s 重复声明且内容冲突' % href, origin,
                                 reference=href)
        target = matches[0]
        if purpose == 'geometry' and not self._is_geometry(target):
            raise FeatureBlocked('not-a-geometry',
                                 '引用目标 %s 不是 GML 几何：%s'
                                 % (href, display_tag(target.tag)), target,
                                 reference=href)
        return target

    def _decode(self, node, stack):
        if node.start in stack:
            raise FeatureBlocked('reference-cycle', '几何引用成环', node)
        if len(stack) > self.max_depth:
            raise FeatureBlocked('nesting-too-deep', '几何嵌套超过限制', node)
        if node.id and self.document.identity_state(node.id) == 'conflict':
            raise FeatureBlocked('duplicate-reference',
                                 'gml:id=%s 在响应中重复声明且内容冲突' % node.id,
                                 node, reference='#' + node.id)
        if node.start in self.cache:
            return self.cache[node.start]
        stack = stack + [node.start]
        kind, value = self._value(node, stack)
        crs = self._crs(node)
        occurrences = self.document.ids.get(node.id, []) if node.id else []
        occurrence = occurrences.index(node) if node in occurrences else 0
        self._counter += 1
        reference = 'g%d' % self._counter
        self.cache[node.start] = reference
        self.geometries.append(dict(
            ref=reference, gml_id=node.id or None, occurrence=occurrence,
            kind=kind, source_tag=display_tag(node.tag),
            source=self._source(node), crs=crs, used_by=[],
            value=dict(value, order='source')))
        return reference

    def _geometry(self, reference):
        return next(entry for entry in self.geometries if entry['ref'] == reference)

    # ---- 几何解码 ---------------------------------------------------------
    def _value(self, node, stack):
        if is_legacy_geometry_tag(node.tag):
            raise FeatureBlocked(
                'unsupported-namespace',
                'GML 3.1 命名空间的几何不能按 GML 3.2 语义解释：' + display_tag(node.tag), node)
        name = local_name(node.tag)
        if name == 'Point':
            return 'Point', dict(position=self._point_position(node))
        if name in ('LineString', 'LinearRing', 'Ring'):
            return 'Curve', dict(segments=[self._segment_positions(node)])
        if name == 'Curve':
            return 'Curve', dict(segments=self._curve_segments(node))
        if name == 'Polygon':
            return 'Polygon', self._polygon(node)
        if name in ('MultiGeometry', 'MultiPoint', 'MultiCurve', 'MultiSurface',
                    'MultiLineString', 'MultiPolygon'):
            return 'Multi', dict(members=self._members(node, stack))
        raise FeatureBlocked('unsupported-geometry',
                             '暂不支持解释该几何元素：' + display_tag(node.tag), node)

    def _point_position(self, node):
        for child in node.children:
            name = local_name(child.tag)
            if name == 'pos':
                positions = self._positions(child.text, self._dimension(node), child)
                if len(positions) != 1:
                    raise FeatureBlocked('dimension-mismatch',
                                         'gml:pos 只能包含一个位置', child)
                return positions[0]
            if name == 'coordinates':
                positions = self._coordinates(child, self._dimension(node))
                if len(positions) != 1:
                    raise FeatureBlocked('dimension-mismatch',
                                         'gml:coordinates 只能包含一个位置', child)
                return positions[0]
        raise FeatureBlocked('empty-geometry', '缺少 gml:pos 或 gml:coordinates', node)

    def _segment_positions(self, node):
        positions = []
        for child in node.children:
            name = local_name(child.tag)
            if name == 'posList':
                positions.extend(self._positions(child.text, self._dimension(node), child))
            elif name == 'pos':
                positions.extend(self._positions(child.text, self._dimension(node), child))
            elif name == 'coordinates':
                positions.extend(self._coordinates(child, self._dimension(node)))
            elif self._is_geometry(child):
                raise FeatureBlocked('unsupported-geometry',
                                     '线段中嵌套了非坐标元素：' + display_tag(child.tag), child)
        if not positions:
            raise FeatureBlocked('empty-geometry', '线段没有坐标', node)
        return positions

    def _curve_segments(self, node):
        holder = next((child for child in node.children
                       if local_name(child.tag) == 'segments'), None)
        if holder is None:
            raise FeatureBlocked('unsupported-geometry',
                                 'gml:Curve 缺少 gml:segments', node)
        segments = []
        for segment in holder.children:
            if local_name(segment.tag) == 'LineStringSegment':
                segments.append(self._segment_positions(segment))
            else:
                raise FeatureBlocked(
                    'unsupported-curve-segment',
                    '曲线段 %s 无法在不伪造坐标的前提下解释' % display_tag(segment.tag),
                    segment)
        if not segments:
            raise FeatureBlocked('empty-geometry', '曲线没有段', node)
        return segments

    def _polygon(self, node):
        exterior = None
        interiors = []
        for child in node.children:
            name = local_name(child.tag)
            if name == 'exterior':
                exterior = self._ring(child)
            elif name == 'interior':
                interiors.append(self._ring(child))
            elif name in ('patches', 'polygonPatch'):
                raise FeatureBlocked('unsupported-geometry',
                                     'SurfacePatch 形式的面暂不解释', child)
        if exterior is None:
            raise FeatureBlocked('missing-exterior', '面缺少外环', node)
        return dict(exterior=exterior, interiors=interiors)

    def _ring(self, node):
        for child in node.children:
            if local_name(child.tag) in ('LinearRing', 'Ring'):
                positions = self._segment_positions(child)
                if len(positions) < 4:
                    raise FeatureBlocked('invalid-ring', '环少于 4 个位置', child)
                if positions[0]['values'] != positions[-1]['values']:
                    raise FeatureBlocked('unclosed-ring', '环首尾坐标不一致', child)
                return positions
        raise FeatureBlocked('invalid-ring', '面环缺少 LinearRing', node)

    def _members(self, node, stack):
        members = []
        parent_crs = self._crs(node)
        for child in node.children:
            name = local_name(child.tag)
            if name in ('geometryMember', 'geometryMembers', 'pointMember',
                        'pointMembers', 'curveMember', 'curveMembers',
                        'surfaceMember', 'surfaceMembers', 'member'):
                href = child.attrs.get(XLINK_HREF)
                if href:
                    target = self._reference(href, child, 'geometry')
                    self._check_nested_crs(parent_crs, target)
                    members.append(self._decode(target, stack))
                    continue
                target = next((item for item in child.children
                               if self._is_geometry(item)), None)
                if target is None:
                    raise FeatureBlocked('invalid-multi',
                                         '多几何成员既没有引用也没有几何元素', child)
                self._check_nested_crs(parent_crs, target)
                members.append(self._decode(target, stack))
            elif self._is_geometry(child):
                # 例如 <gml:MultiGeometry><gml:Point/>...</gml:MultiGeometry>
                self._check_nested_crs(parent_crs, child)
                members.append(self._decode(child, stack))
        if not members:
            raise FeatureBlocked('empty-geometry', '多几何没有成员', node)
        return members

    def _check_nested_crs(self, parent, member):
        """嵌套几何声明的 CRS 与父几何不同则拒绝：同一坐标数组不能混用轴序。"""
        nested = self._crs(member)
        if parent['srsName'] and nested['srsName'] and parent['srsName'] != nested['srsName']:
            raise FeatureBlocked(
                'crs-conflict',
                '嵌套几何声明 %s 与父几何 %s 不同，拒绝混合轴序'
                % (nested['srsName'], parent['srsName']), member)

    # ---- 坐标文本 ---------------------------------------------------------
    def _dimension(self, node):
        return self._crs(node)['dimension'] or 2

    def _positions(self, text, dimension, node):
        tokens = text.split()
        if not tokens:
            raise FeatureBlocked('empty-geometry', '坐标文本为空', node)
        if dimension is None or dimension < 1:
            raise FeatureBlocked('dimension-mismatch', '坐标维度无法确定', node)
        if len(tokens) % dimension:
            raise FeatureBlocked('dimension-mismatch',
                                 '坐标数值个数 %d 不是声明维度 %d 的整数倍'
                                 % (len(tokens), dimension), node)
        values = []
        for token in tokens:
            try:
                number = float(token)
            except ValueError:
                raise FeatureBlocked('invalid-coordinate',
                                     '坐标含非数值：' + token, node) from None
            if number != number or number in (float('inf'), float('-inf')):
                raise FeatureBlocked('invalid-coordinate',
                                     '坐标含非有限值：' + token, node)
            values.append(number)
        return [dict(raw=' '.join(tokens[index:index + dimension]),
                     values=values[index:index + dimension])
                for index in range(0, len(values), dimension)]

    def _coordinates(self, node, dimension):
        if (node.attrs.get('decimal', '.') != '.'
                or node.attrs.get('cs', ',') != ','):
            raise FeatureBlocked('unsupported-coordinates-format',
                                 'gml:coordinates 使用非默认分隔符，未做解释', node)
        positions = []
        for tuple_text in node.text.split(node.attrs.get('ts', ' ')):
            if not tuple_text:
                continue
            parts = tuple_text.split(',')
            if dimension is not None and len(parts) != dimension:
                raise FeatureBlocked('dimension-mismatch',
                                     'gml:coordinates 元组维度与声明不符', node)
            try:
                values = [float(part) for part in parts]
            except ValueError:
                raise FeatureBlocked('invalid-coordinate',
                                     'gml:coordinates 含非数值', node) from None
            positions.append(dict(raw=tuple_text, values=values))
        if not positions:
            raise FeatureBlocked('empty-geometry', 'gml:coordinates 为空', node)
        return positions

    # ---- CRS --------------------------------------------------------------
    def _crs(self, node):
        srs_name = None
        dimension_text = None
        declared_at = None
        current = node
        while current is not None:
            if srs_name is None and current.attrs.get('srsName'):
                srs_name = current.attrs['srsName']
                declared_at = current
            if dimension_text is None and current.attrs.get('srsDimension'):
                dimension_text = current.attrs['srsDimension']
            current = current.parent
        origin = None
        if declared_at is not None:
            origin = dict(where='self' if declared_at is node else 'ancestor',
                          tag=display_tag(declared_at.tag),
                          start_byte=declared_at.start)
        if dimension_text is not None:
            try:
                dimension = int(dimension_text)
            except ValueError:
                return dict(srsName=srs_name, dimension=None, status='unknown',
                            axis_order=None, declared_at=origin,
                            detail='srsDimension 不是整数')
            if dimension < 1:
                return dict(srsName=srs_name, dimension=None, status='unknown',
                            axis_order=None, declared_at=origin,
                            detail='srsDimension 小于 1')
        else:
            dimension = 2  # GML 默认二维
        base = dict(srsName=srs_name, dimension=dimension, declared_at=origin)
        if not srs_name:
            return dict(base, status='missing', axis_order=None,
                        detail='来源没有声明 srsName，不能证明轴顺序')
        entries = self.crs.get(srs_name)
        if entries is None:
            return dict(base, status='unknown', axis_order=None,
                        detail='srsName 未登记，不能证明轴顺序，未做任何换算')
        axes = entries.get(dimension)
        if axes is None:
            return dict(base, status='unsupported-dimension', axis_order=None,
                        detail='已登记 CRS 没有 %d 维的轴顺序定义' % dimension)
        return dict(base, status='verified', axis_order=list(axes), detail=None)


# ---- GeoJSON 导出 ---------------------------------------------------------

class ConversionError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def to_geojson(collection):
    """按已证明的轴顺序把几何重排为 GeoJSON 的经、纬（+可选高程）。

    不能证明轴顺序、引用未解析或几何损坏的要素保留在输出中，geometry 为 null，
    并给出 reason 与响应节点位置，不会被静默丢弃或换成看似合理的位置。
    """
    by_ref = {entry['ref']: entry for entry in collection['geometries']}
    features = []
    not_converted = []
    for item in collection['features']:
        names = {}
        for entry in item['properties']:
            if entry['name'] not in names:
                names[entry['name']] = entry['value']
                continue
            existing = names[entry['name']]
            if isinstance(existing, list):
                existing.append(entry['value'])
            else:
                names[entry['name']] = [existing, entry['value']]
        if item.get('reference'):
            names['reference'] = item['reference']
        feature = dict(type='Feature', id=item['id'],
                       properties=dict(source=item['source'], properties=names),
                       geometry=None)
        reason = None
        entry = by_ref.get(item.get('geometry_ref')) if item.get('geometry_ref') else None
        if item['status'] != 'go':
            reason = dict(item['reason'])
        elif entry is None:
            feature['properties']['note'] = '该要素没有几何，按 GeoJSON 允许的 null geometry 导出'
        elif entry['crs']['status'] != 'verified':
            reason = dict(code=entry['crs']['status'] + '-crs',
                          detail=entry['crs']['detail'], source=entry['source'])
        else:
            try:
                converted = _convert(entry, entry['crs']['axis_order'], by_ref, [])
            except ConversionError as error:
                reason = dict(code=error.code, detail=str(error), source=entry['source'])
            else:
                feature['geometry'] = converted
                feature['properties']['source_crs'] = dict(
                    srsName=entry['crs']['srsName'],
                    axis_order=entry['crs']['axis_order'],
                    dimension=entry['crs']['dimension'],
                    output='GeoJSON 位置顺序固定为 [经度, 纬度, 可选高程]')
        if reason is not None:
            feature['reason'] = reason
            not_converted.append(dict(id=item['id'], reason=reason))
        features.append(feature)
    return dict(type='FeatureCollection', features=features,
                converted=len(features) - len(not_converted),
                not_converted=not_converted,
                source=collection['source'], page=collection['page'],
                crs=collection['crs'])


def _convert(entry, axes, by_ref, stack):
    if entry['ref'] in stack:
        raise ConversionError('reference-cycle', '导出几何引用成环')
    stack = stack + [entry['ref']]
    kind = entry['kind']
    value = entry['value']
    if kind == 'Point':
        return dict(type='Point', coordinates=_position(value['position'], axes))
    if kind == 'Curve':
        lines = [[_position(position, axes) for position in segment]
                 for segment in value['segments']]
        if not lines:
            raise ConversionError('empty-geometry', '曲线没有可导出的坐标')
        if len(lines) == 1:
            return dict(type='LineString', coordinates=lines[0])
        return dict(type='MultiLineString', coordinates=lines)
    if kind == 'Polygon':
        rings = [value['exterior']] + value['interiors']
        return dict(type='Polygon', coordinates=[
            [_position(position, axes) for position in ring] for ring in rings])
    if kind == 'Multi':
        converted = [_convert(by_ref[reference], axes, by_ref, stack)
                     for reference in value['members']]
        types = {item['type'] for item in converted}
        if len(converted) == 1:
            return converted[0]
        if types <= {'Point'}:
            return dict(type='MultiPoint',
                        coordinates=[item['coordinates'] for item in converted])
        if types <= {'LineString'}:
            return dict(type='MultiLineString',
                        coordinates=[item['coordinates'] for item in converted])
        if types <= {'Polygon'}:
            return dict(type='MultiPolygon',
                        coordinates=[item['coordinates'] for item in converted])
        return dict(type='GeometryCollection', geometries=converted)
    raise ConversionError('unsupported-geometry', '未知几何类型：' + str(kind))


def _position(position, axes):
    values = position['values']
    if len(values) != len(axes):
        raise ConversionError('dimension-mismatch', '坐标维度与轴顺序定义不符')
    ordered = dict(zip(axes, values))
    if 'lon' not in ordered or 'lat' not in ordered:
        raise ConversionError('unknown-axis', '轴顺序定义缺少经度或纬度')
    output = [ordered['lon'], ordered['lat']]
    if 'h' in ordered:
        output.append(ordered['h'])
    return output

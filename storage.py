import hashlib
import json
import sqlite3


class Archive:
    """原件与结构化采集结果的本地留存。

    `captures` 保存字节、来源、摘要与兼容的结构检查行；`pages` 保存页面完整性判断；
    `geometries` 保存几何引用身份（同一来源对象在多个要素间复用时 ref 相同）及其
    坐标语义状态。重复原件按来源与摘要合并为同一收件编号。
    """

    def __init__(self, path):
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.executescript(
            'CREATE TABLE IF NOT EXISTS captures('
            'id INTEGER PRIMARY KEY, source TEXT NOT NULL, digest TEXT NOT NULL,'
            'raw BLOB NOT NULL, rows_json TEXT NOT NULL, UNIQUE(source,digest));'
            'CREATE TABLE IF NOT EXISTS pages('
            'capture_id INTEGER PRIMARY KEY REFERENCES captures(id),'
            'complete INTEGER NOT NULL, page_json TEXT NOT NULL);'
            'CREATE TABLE IF NOT EXISTS geometries('
            'capture_id INTEGER NOT NULL REFERENCES captures(id),'
            'ref TEXT NOT NULL, gml_id TEXT, kind TEXT NOT NULL,'
            'crs_status TEXT NOT NULL, srs_name TEXT, axis_order TEXT,'
            'start_byte INTEGER, end_byte INTEGER, used_by_json TEXT NOT NULL,'
            'PRIMARY KEY(capture_id,ref));')

    def save(self, source, raw, rows, collection=None):
        if not source.strip():
            raise ValueError('来源标识不能为空')
        digest = hashlib.sha256(raw).hexdigest()
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute(
                'INSERT OR IGNORE INTO captures(source,digest,raw,rows_json) VALUES(?,?,?,?)',
                (source, digest, raw, payload))
            record = self.connection.execute(
                'SELECT id FROM captures WHERE source=? AND digest=?', (source, digest)).fetchone()
            capture_id = record[0]
            if collection is not None:
                self.connection.execute(
                    'INSERT OR REPLACE INTO pages(capture_id,complete,page_json) VALUES(?,?,?)',
                    (capture_id, int(bool(collection['page']['complete'])),
                     json.dumps(collection['page'], ensure_ascii=False, sort_keys=True)))
                for geometry in collection['geometries']:
                    crs = geometry['crs']
                    self.connection.execute(
                        'INSERT OR IGNORE INTO geometries(capture_id,ref,gml_id,kind,'
                        'crs_status,srs_name,axis_order,start_byte,end_byte,used_by_json)'
                        ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (capture_id, geometry['ref'], geometry['gml_id'], geometry['kind'],
                         crs['status'], crs['srsName'],
                         json.dumps(crs['axis_order']) if crs['axis_order'] else None,
                         geometry['source']['start_byte'], geometry['source']['end_byte'],
                         json.dumps(geometry.get('used_by', []), sort_keys=True)))
        return capture_id

    def list(self):
        return [dict(id=row[0], source=row[1], digest=row[2], rows=json.loads(row[3]))
                for row in self.connection.execute(
                    'SELECT id,source,digest,rows_json FROM captures ORDER BY id')]

    def pages(self):
        return [dict(capture_id=row[0], complete=bool(row[1]), page=json.loads(row[2]))
                for row in self.connection.execute(
                    'SELECT capture_id,complete,page_json FROM pages ORDER BY capture_id')]

    def geometries(self, capture_id):
        return [dict(ref=row[0], gml_id=row[1], kind=row[2], crs_status=row[3],
                     srs_name=row[4],
                     axis_order=json.loads(row[5]) if row[5] else None,
                     start_byte=row[6], end_byte=row[7],
                     used_by=json.loads(row[8]))
                for row in self.connection.execute(
                    'SELECT ref,gml_id,kind,crs_status,srs_name,axis_order,start_byte,'
                    'end_byte,used_by_json FROM geometries WHERE capture_id=? ORDER BY ref',
                    (capture_id,))]

    def raw(self, capture_id):
        row = self.connection.execute('SELECT raw FROM captures WHERE id=?', (capture_id,)).fetchone()
        if row is None:
            raise KeyError(capture_id)
        return bytes(row[0])

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

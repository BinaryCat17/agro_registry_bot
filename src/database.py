import sqlite3
import json
import math
import os

def _yo_pattern(pattern: str):
    """Заменяет е/ё на регексный класс [её] для взаимозаменяемого поиска."""
    return ''.join('[её]' if c in 'её' else c for c in pattern)

class RegistryDatabase:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.db_path = os.path.join(base_dir, "data", "reestr.db")
        else:
            self.db_path = db_path
        self.conn = None

    def _connect(self):
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            import re
            def regexp(expr, item):
                if item is None:
                    return False
                return re.compile(expr, re.IGNORECASE).search(str(item)) is not None
            self.conn.create_function("REGEXP", 2, regexp)
            self.conn.create_function("LOWER", 1, lambda x: str(x).lower() if x is not None else None)
            self.conn.create_function("UPPER", 1, lambda x: str(x).upper() if x is not None else None)
            self.conn.create_function("LN", 1, lambda x: math.log(x) if x is not None and x > 0 else 0)
            self.conn.create_function("LOG", 1, lambda x: math.log10(x) if x is not None and x > 0 else 0)
            # Таблицы популярности для совместимости с AI-агентом
            self.conn.execute("CREATE TABLE IF NOT EXISTS product_popularity (naimenovanie TEXT PRIMARY KEY, score INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
            self.conn.execute("CREATE TABLE IF NOT EXISTS agrokhimikaty_popularity (preparat TEXT PRIMARY KEY, score INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
            self.conn.commit()
        return self.conn

    def execute_query(self, query: str):
        return self.execute(query)

    def execute(self, query: str, params=()):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(query, params)
            q_upper = query.strip().upper()
            is_select = any(q_upper.startswith(word) for word in ["SELECT", "WITH", "PRAGMA", "EXPLAIN"])
            if is_select:
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            conn.commit()
            return {"status": "success", "rows_affected": cur.rowcount}
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            return {"error": str(e)}

    def get_schema(self):
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = cur.fetchall()
            if not tables:
                return "No tables found."
            schema = []
            for (table_name,) in tables:
                cur.execute(f"PRAGMA table_info({table_name});")
                cols = cur.fetchall()
                schema.append(f"Table: {table_name}")
                for col in cols:
                    schema.append(f"  - {col['name']} ({col['type']})")
            return "\n".join(schema)
        except Exception as e:
            return f"Error: {str(e)}"

    def last_update_time(self):
        query = """
            SELECT MAX(imported_at) as last_update FROM (
                SELECT imported_at FROM agrokhimikaty
                UNION ALL
                SELECT imported_at FROM pestitsidy
            )
        """
        res = self.execute(query)
        return res[0]["last_update"] if res else None

    def stats(self):
        stats = {}
        for table in ["agrokhimikaty", "agrokhimikaty_primeneniya", "pestitsidy", "pestitsidy_primeneniya"]:
            res = self.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            stats[table] = res[0]["cnt"] if isinstance(res, list) and res else 0
        return stats

    def find_pesticide_by_name(self, name: str, active_only=True, limit=10, offset=0):
        where = "p.naimenovanie REGEXP ?"
        if active_only:
            where += " AND p.status = 'Действует'"
        query = f"""
            SELECT p.id, p.nomer_reg, p.naimenovanie, p.deystvuyushchee_veshchestvo,
                   p.registrant, p.status, p.srok_reg, p.preparativnaya_forma
            FROM pestitsidy p
            WHERE {where}
            ORDER BY p.naimenovanie
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(name),))

    def find_pesticide_by_dv(self, substance: str, active_only=True, limit=15, offset=0):
        where = "exists (SELECT 1 FROM json_each(p.deystvuyushchee_veshchestvo) dv WHERE dv.value->>'veshchestvo' REGEXP ?)"
        if active_only:
            where += " AND p.status = 'Действует'"
        query = f"""
            SELECT p.id, p.nomer_reg, p.naimenovanie, p.deystvuyushchee_veshchestvo,
                   p.registrant, p.status, p.srok_reg
            FROM pestitsidy p
            WHERE {where}
            ORDER BY p.naimenovanie
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(substance),))

    def find_pesticide_applications(self, nomer_reg: str):
        query = """
            SELECT vrednyy_obekt, kultura, sposob, norma, srok_ozhidaniya, vyhod, osobennosti
            FROM pestitsidy_primeneniya
            WHERE nomer_reg = ?
            ORDER BY kultura
        """
        return self.execute(query, (nomer_reg,))

    def find_agrochemical_by_name(self, name: str, active_only=True, limit=10, offset=0):
        where = "preparat REGEXP ?"
        if active_only:
            where += " AND status = 'Действует'"
        query = f"""
            SELECT id, rn, preparat, registrant, status, srok_reg, group_name
            FROM agrokhimikaty
            WHERE {where}
            ORDER BY preparat
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(name),))

    def find_agrochemical_applications(self, rn: str):
        query = """
            SELECT marka, oblast, doza, kultura, vremya, osobennosti
            FROM agrokhimikaty_primeneniya
            WHERE rn = ?
            ORDER BY kultura
        """
        return self.execute(query, (rn,))

    def search_pesticides_by_crop(self, crop: str, active_only=True, limit=15, offset=0):
        where = "pp.kultura REGEXP ?"
        if active_only:
            where += " AND p.status = 'Действует'"
        query = f"""
            SELECT DISTINCT p.id, p.nomer_reg, p.naimenovanie, p.deystvuyushchee_veshchestvo,
                   p.registrant, p.status, p.srok_reg
            FROM pestitsidy p
            JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg
            WHERE {where}
            ORDER BY p.naimenovanie
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(crop),))

    def search_agrochemicals_by_crop(self, crop: str, active_only=True, limit=15, offset=0):
        where = "ap.kultura REGEXP ?"
        if active_only:
            where += " AND a.status = 'Действует'"
        query = f"""
            SELECT DISTINCT a.id, a.rn, a.preparat, a.registrant, a.status, a.srok_reg, a.group_name
            FROM agrokhimikaty a
            JOIN agrokhimikaty_primeneniya ap ON a.rn = ap.rn
            WHERE {where}
            ORDER BY a.preparat
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(crop),))

    def search_pesticides_by_pest(self, pest: str, active_only=True, limit=15, offset=0):
        where = "pp.vrednyy_obekt REGEXP ?"
        if active_only:
            where += " AND p.status = 'Действует'"
        query = f"""
            SELECT DISTINCT p.id, p.nomer_reg, p.naimenovanie, p.deystvuyushchee_veshchestvo,
                   p.registrant, p.status, p.srok_reg
            FROM pestitsidy p
            JOIN pestitsidy_primeneniya pp ON p.nomer_reg = pp.nomer_reg
            WHERE {where}
            ORDER BY p.naimenovanie
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute(query, (_yo_pattern(pest),))

    def __del__(self):
        if self.conn:
            self.conn.close()

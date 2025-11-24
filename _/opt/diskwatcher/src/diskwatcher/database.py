import sqlite3
import hashlib


class Database:
    """Handles SQLite interactions for disk events"""

    TABLES = ['disk_event']
    DEFAULT_SCHEMA = [
"""
CREATE TABLE disk_event
(
id_event INTEGER PRIMARY KEY,
dev varchar(32) NOT NULL,
serial varchar(128) NOT NULL,
serial_md5 char(32) NOT NULL,

dt datetime,
dt_boot datetime,

smart_json TEXT
);
""",
"""
CREATE INDEX idiskevent_dt_disk_serial ON disk_event(serial_md5, dt, id_event);
"""
    ]
    
    def __init__(self, db_path:str):
        self.db_path = db_path

        try:
            self._setup_connection()
            self._create_tables()
        except sqlite3.Error as e:
            raise sqlite3.Error(f"Database init failed: {e}")

    def _setup_connection(self, timeout:int = 3):
        # def dict_factory(self, cursor, row):
        #     d = {}
        #     for idx, col in enumerate(cursor.description):
        #         d[col[0]] = row[idx]
        #     return d

        self.conn = sqlite3.connect(self.db_path, timeout=timeout)
        #self.conn.row_factory = dict_factory
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def _create_tables(self):
        sql = "SELECT name FROM sqlite_master WHERE type='table'"
        self.cursor.execute(sql)
        res = self.cursor.fetchall()

        tables = list()
        for col in res:
            tables.append(col['name'])

        if not all(item in tables for item in self.TABLES):
            for table in self.DEFAULT_SCHEMA:
                self.cursor.execute(table)
            self.conn.commit()

    def get_last_events(self, serial):
        sql = 'SELECT * FROM disk_event WHERE serial_md5 = :serial_md5 ORDER BY dt DESC,id_event DESC LIMIT 2'
        self.cursor.execute(sql, {'serial_md5': hashlib.md5(serial.encode()).hexdigest()} )
        val = self.cursor.fetchall()

        return val

    def store_event(self, data:dict):
        sql = """INSERT INTO disk_event (id_event, dev, serial, serial_md5, dt, dt_boot, smart_json) 
        VALUES(null,:dev,:serial,:serial_md5,datetime('now'),:dt_boot,:smart_json)"""

        data['serial_md5'] = hashlib.md5(data['serial'].encode()).hexdigest()

        self.cursor.execute(sql, data)
        self.conn.commit()

    def close(self):
        self.conn.close()


"""NOTE: Reusing cursor"""
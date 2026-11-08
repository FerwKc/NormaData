"""Historial local independiente de las bases SQL Server evaluadas."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AuditHistory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS Regla (
                    id_regla INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL,
                    nombre TEXT NOT NULL, descripcion TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS Auditoria (
                    id_auditoria INTEGER PRIMARY KEY, fecha TEXT NOT NULL, servidor TEXT NOT NULL,
                    base_datos_evaluada TEXT NOT NULL, cantidad_tablas_analizadas INTEGER NOT NULL,
                    puntuacion_normalizacion INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS Hallazgo (
                    id_hallazgo INTEGER PRIMARY KEY, id_auditoria INTEGER NOT NULL REFERENCES Auditoria,
                    id_regla INTEGER NOT NULL REFERENCES Regla, tabla_afectada TEXT NOT NULL,
                    descripcion_detalle TEXT NOT NULL);
            """)
    def save(self, server, result):
        with sqlite3.connect(self.path) as c:
            c.execute("PRAGMA foreign_keys=ON")
            cur = c.execute("INSERT INTO Auditoria VALUES(NULL,?,?,?,?,?)", (
                datetime.now(timezone.utc).isoformat(), server, result.database,
                result.tables_analyzed, result.score))
            audit_id = cur.lastrowid
            for f in result.findings:
                c.execute("INSERT OR IGNORE INTO Regla(codigo,nombre,descripcion) VALUES(?,?,?)",
                          (f.rule, f.rule, "Regla de diagnóstico NORMADATA"))
                rid = c.execute("SELECT id_regla FROM Regla WHERE codigo=?", (f.rule,)).fetchone()[0]
                c.execute("INSERT INTO Hallazgo VALUES(NULL,?,?,?,?)",
                          (audit_id, rid, f.table, f.message+' '+f.evidence))
            return audit_id
    def list(self):
        with sqlite3.connect(self.path) as c:
            return c.execute("""SELECT a.fecha,a.base_datos_evaluada,a.cantidad_tablas_analizadas,
                COUNT(h.id_hallazgo) FROM Auditoria a LEFT JOIN Hallazgo h USING(id_auditoria)
                GROUP BY a.id_auditoria ORDER BY a.id_auditoria DESC""").fetchall()

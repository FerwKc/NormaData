from dataclasses import replace
from src.models import Column, TableMetadata


class SQLServerUnavailable(RuntimeError):
    pass


class SQLServerClient:
    def __init__(self, server: str, port: str, user: str, password: str, read_only: bool = True) -> None:
        self.server = server.strip()
        self.port = port.strip()
        self.user = user.strip()
        self.password = password
        self.read_only = read_only
        self._pyodbc = self._load_pyodbc()

    def _load_pyodbc(self):
        try:
            import pyodbc  # type: ignore
        except ImportError as exc:
            import sys

            raise SQLServerUnavailable(
                "pyodbc no está instalado en el Python que ejecutó NORMADATA.\n\n"
                f"Intérprete activo: {sys.executable}\n\n"
                "Cierre esta ventana y ejecute run.bat, o instale las dependencias con:\n"
                "python -m pip install -r requirements.txt"
            ) from exc
        return pyodbc

    def _connection_string(self, database: str = "master") -> str:
        server_target = self.server if not self.port else f"{self.server},{self.port}"
        read_only_option = "ApplicationIntent=ReadOnly;" if self.read_only else ""
        return (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={_odbc_value(server_target)};"
            f"DATABASE={_odbc_value(database)};"
            f"UID={_odbc_value(self.user)};"
            f"PWD={_odbc_value(self.password)};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            f"{read_only_option}"
        )

    def execute_remediation(self, database: str, transactional_sql: str) -> None:
        if self.read_only:
            raise PermissionError(
                "La conexión actual es de solo lectura. Vuelva a conectar en modo Remediación Activa."
            )
        if not transactional_sql.strip():
            raise ValueError("El script de remediación está vacío.")
        if "\nGO\n" in f"\n{transactional_sql.upper()}\n":
            raise ValueError("Los separadores GO no están permitidos en una ejecución transaccional.")
        raise ValueError("Utilice execute_plan con un plan generado y su tabla de origen; "
                         "no se admite ejecución de texto SQL arbitrario.")

    def resource_preflight(self, database: str, table: str) -> dict:
        with self._pyodbc.connect(self._connection_string(database), timeout=10,
                                  autocommit=True) as connection:
            return self._resource_preflight(connection.cursor(), table)

    @staticmethod
    def _resource_preflight(cursor, table: str) -> dict:
        row = cursor.execute("""SELECT total_log_size_in_bytes,used_log_space_in_bytes
            FROM sys.dm_db_log_space_usage""").fetchone()
        if row is None:
            raise PermissionError("No hay visibilidad del log; ejecución rechazada.")
        size = cursor.execute("""SELECT SUM(CONVERT(bigint,used_page_count))*8192
            FROM sys.dm_db_partition_stats WHERE object_id=OBJECT_ID(?)""", table).fetchone()[0]
        if not size:
            raise ValueError("La tabla no existe, no es visible o no tiene páginas asignadas.")
        free = int(row[0])-int(row[1])
        return {"table_bytes":int(size), "log_total_bytes":int(row[0]),
                "log_used_bytes":int(row[1]), "log_free_bytes":free,
                "required_bytes":2*int(size), "allowed":free>=2*int(size)}

    def execute_plan(self, database: str, plan, *, rollback_only: bool = False) -> dict:
        if self.read_only:
            raise PermissionError("Modo Auditoría: ejecución de cambios bloqueada antes de enviar SQL.")
        from src.remediation import build_remediation_plan, wrap_transaction
        if not plan.executable or plan.finding is None:
            raise PermissionError("Este plan requiere revisión manual y no admite ejecución.")
        current = next((t for t in self.load_metadata(database) if t.full_name==plan.table),None)
        if current is None:
            raise ValueError("La tabla de origen ya no está disponible.")
        # Regenerate the plan from fresh metadata; prevent stale or edited SQL.
        regenerated = build_remediation_plan(plan.finding,current)
        if not regenerated.executable or regenerated.sql!=plan.sql:
            raise ValueError("El esquema o el plan cambió; genere una nueva vista previa.")
        with self._pyodbc.connect(self._connection_string(database),timeout=15,
                                  autocommit=True) as connection:
            connection.timeout=30
            cursor=connection.cursor()
            preflight=self._resource_preflight(cursor,plan.table)
            if not preflight["allowed"]:
                raise RuntimeError("Reserva de log insuficiente: se exige libre >= 200 % del tamaño de tabla e índices.")
            try:
                if cursor.execute("SELECT @@TRANCOUNT").fetchone()[0]!=0:
                    raise RuntimeError("La sesión contiene una transacción previa.")
                cursor.execute(wrap_transaction(plan.sql,rollback_only=rollback_only))
                while cursor.nextset():
                    pass
                if cursor.execute("SELECT @@TRANCOUNT").fetchone()[0]!=0:
                    raise RuntimeError("La transacción no se cerró correctamente.")
            except Exception:
                try: cursor.execute("IF XACT_STATE()<>0 ROLLBACK TRANSACTION;")
                except Exception: pass
                raise
            return {**preflight,"outcome":"ROLLBACK" if rollback_only else "COMMIT"}

    def test_connection(self) -> None:
        with self._pyodbc.connect(self._connection_string(), timeout=5) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def list_databases(self) -> list[str]:
        query = """
            SELECT name
            FROM sys.databases
            WHERE database_id > 4
              AND state_desc = 'ONLINE'
            ORDER BY name
        """
        with self._pyodbc.connect(self._connection_string(), timeout=8) as connection:
            cursor = connection.cursor()
            cursor.execute(query)
            return [row[0] for row in cursor.fetchall()]

    def load_metadata(self, database: str) -> list[TableMetadata]:
        with self._pyodbc.connect(self._connection_string(database), timeout=12) as connection:
            cursor = connection.cursor()
            tables = self._read_tables(cursor)
            pk_columns = self._read_primary_keys(cursor)
            fk_columns = self._read_foreign_keys(cursor)
            columns_by_table = self._read_columns(cursor, pk_columns, fk_columns)
            candidate_keys = self._read_candidate_keys(cursor)
            return [
                TableMetadata(schema=schema, name=name, columns=tuple(columns_by_table[(schema, name)]),
                              candidate_keys=tuple(candidate_keys.get((schema,name),())))
                for schema, name in tables
            ]

    def _read_tables(self, cursor) -> list[tuple[str, str]]:
        cursor.execute(
            """
            SELECT s.name AS schema_name, t.name AS table_name
            FROM sys.tables t
            INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE t.is_ms_shipped = 0
            ORDER BY s.name, t.name
            """
        )
        return [(row.schema_name, row.table_name) for row in cursor.fetchall()]

    def _read_columns(self, cursor, pk_columns, fk_columns) -> dict[tuple[str, str], list[Column]]:
        cursor.execute(
            """
            SELECT
                s.name AS schema_name,
                t.name AS table_name,
                c.name AS column_name,
                ty.name AS data_type,
                c.is_nullable,
                c.max_length,c.precision,c.scale
            FROM sys.tables t
            INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
            INNER JOIN sys.columns c ON c.object_id = t.object_id
            INNER JOIN sys.types ty ON ty.user_type_id = c.user_type_id
            WHERE t.is_ms_shipped = 0
            ORDER BY s.name, t.name, c.column_id
            """
        )
        grouped: dict[tuple[str, str], list[Column]] = {}
        for row in cursor.fetchall():
            table_key = (row.schema_name, row.table_name)
            column_key = (row.schema_name, row.table_name, row.column_name)
            fk_info = fk_columns.get(column_key, {})
            grouped.setdefault(table_key, []).append(
                Column(
                    name=row.column_name,
                    data_type=row.data_type,
                    nullable=bool(row.is_nullable),
                    max_length=row.max_length,
                    is_primary_key=column_key in pk_columns,
                    is_foreign_key=column_key in fk_columns,
                    references_table=fk_info.get("references_table"),
                    references_column=fk_info.get("references_column"),
                    precision=int(row.precision), scale=int(row.scale),
                )
            )
        return grouped

    def profile_tables(self, database: str, tables: list[TableMetadata], limit: int=1000):
        limit=max(2,min(int(limit),10000))
        profiled=[]
        with self._pyodbc.connect(self._connection_string(database),timeout=15) as connection:
            connection.timeout=20
            cursor=connection.cursor()
            for table in tables:
                names=[c.name for c in table.columns if c.data_type.lower() not in
                       {"image","binary","varbinary","timestamp","rowversion","geography","geometry","hierarchyid"}]
                if not names:
                    profiled.append(replace(table,profile_error="Sin atributos compatibles para perfilado."));continue
                quoted=', '.join(quote_identifier(n) for n in names)
                qualified=quote_identifier(table.schema)+'.'+quote_identifier(table.name)
                order=', '.join(quote_identifier(c.name) for c in table.primary_key_columns)
                query=f"SELECT TOP ({limit+1}) {quoted} FROM {qualified}"+(f" ORDER BY {order}" if order else "")
                try:
                    raw=cursor.execute(query).fetchall()
                    rows=tuple(dict(zip(names,row)) for row in raw[:limit])
                    profiled.append(replace(table,sample_rows=rows,sample_complete=len(raw)<=limit))
                except Exception as exc:
                    profiled.append(replace(table,profile_error=type(exc).__name__+": perfilado no disponible"))
            connection.rollback()  # closes the read transaction, never commits changes
        return profiled

    def _read_candidate_keys(self,cursor):
        cursor.execute("""SELECT s.name AS schema_name,t.name AS table_name,i.index_id,
            c.name AS column_name,c.is_nullable,ic.key_ordinal
            FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
            JOIN sys.indexes i ON i.object_id=t.object_id
            JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
            JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
            WHERE t.is_ms_shipped=0 AND i.is_unique=1 AND i.has_filter=0
                AND i.is_disabled=0 AND ic.key_ordinal>0 AND ic.is_included_column=0
            ORDER BY s.name,t.name,i.index_id,ic.key_ordinal""")
        groups={}
        for r in cursor.fetchall():
            groups.setdefault((r.schema_name,r.table_name,r.index_id),[]).append((r.column_name,bool(r.is_nullable)))
        keys={}
        for (schema,name,_),columns in groups.items():
            if not any(nullable for _,nullable in columns):
                keys.setdefault((schema,name),[]).append(tuple(n for n,_ in columns))
        for table,items in keys.items():
            keys[table]=[key for key in items if not any(set(other)<set(key) for other in items)]
        return keys

    def _read_primary_keys(self, cursor) -> set[tuple[str, str, str]]:
        cursor.execute(
            """
            SELECT s.name AS schema_name, t.name AS table_name, c.name AS column_name
            FROM sys.key_constraints kc
            INNER JOIN sys.tables t ON t.object_id = kc.parent_object_id
            INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
            INNER JOIN sys.index_columns ic ON ic.object_id = t.object_id AND ic.index_id = kc.unique_index_id
            INNER JOIN sys.columns c ON c.object_id = t.object_id AND c.column_id = ic.column_id
            WHERE kc.type = 'PK'
            """
        )
        return {(row.schema_name, row.table_name, row.column_name) for row in cursor.fetchall()}

    def _read_foreign_keys(self, cursor) -> dict[tuple[str, str, str], dict[str, str]]:
        cursor.execute(
            """
            SELECT
                ps.name AS schema_name,
                pt.name AS table_name,
                pc.name AS column_name,
                rt.name AS references_table,
                rc.name AS references_column
            FROM sys.foreign_key_columns fkc
            INNER JOIN sys.tables pt ON pt.object_id = fkc.parent_object_id
            INNER JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
            INNER JOIN sys.columns pc ON pc.object_id = pt.object_id AND pc.column_id = fkc.parent_column_id
            INNER JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id
            INNER JOIN sys.columns rc ON rc.object_id = rt.object_id AND rc.column_id = fkc.referenced_column_id
            """
        )
        return {
            (row.schema_name, row.table_name, row.column_name): {
                "references_table": row.references_table,
                "references_column": row.references_column,
            }
            for row in cursor.fetchall()
        }


def _odbc_value(value: str) -> str:
    """Protege valores ODBC que contienen punto y coma o llaves."""
    return "{" + str(value).replace("}", "}}") + "}"


def quote_identifier(value: str) -> str:
    return '['+str(value).replace(']',']]')+']'

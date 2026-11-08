import re
from dataclasses import dataclass

from src.models import Column, Finding, TableMetadata


@dataclass(frozen=True)
class RemediationPlan:
    title: str
    table: str
    sql: str
    risks: tuple[str, ...]
    executable: bool = True
    finding: Finding | None = None

    @property
    def wrapped_sql(self) -> str:
        return wrap_transaction(self.sql)


def build_remediation_plan(
    finding: Finding,
    table_metadata: TableMetadata | None = None,
) -> RemediationPlan:
    schema, table = _split_table(finding.table)
    qualified = f"{_quote(schema)}.{_quote(table)}"

    if "no tiene una clave primaria" in finding.message.lower():
        column = _safe_name(f"normadata_{table}_id", 120)
        constraint = _safe_name(f"PK_{table}_Normadata", 120)
        sql = (
            f"ALTER TABLE {qualified}\n"
            f"ADD {_quote(column)} BIGINT IDENTITY(1,1) NOT NULL;\n\n"
            f"ALTER TABLE {qualified}\n"
            f"ADD CONSTRAINT {_quote(constraint)} PRIMARY KEY ({_quote(column)});"
        )
        return RemediationPlan(
            title="Crear clave primaria técnica",
            table=finding.table,
            sql=sql,
            risks=(
                "Puede bloquear la tabla mientras SQL Server agrega y valida la nueva columna.",
                "La clave técnica no sustituye la validación de una clave natural del negocio.",
                "Índices, replicación y procesos ETL deben revisarse después del cambio.",
            ),
            finding=finding,
        )

    repeated_columns = _extract_repeated_columns(finding.message)
    if repeated_columns:
        return _build_repeated_columns_plan(
            finding, schema, table, qualified, repeated_columns, table_metadata
        )

    column = _extract_quoted_name(finding.message)
    if column and "multivalor" in finding.message.lower():
        child = _safe_name(f"{table}_{column}_Item", 120)
        child_qualified = f"{_quote(schema)}.{_quote(child)}"
        pk = _safe_name(f"PK_{child}", 120)
        sql = (
            f"CREATE TABLE {child_qualified} (\n"
            f"    [item_id] BIGINT IDENTITY(1,1) NOT NULL,\n"
            f"    [source_row_key] NVARCHAR(450) NOT NULL,\n"
            f"    [value] NVARCHAR(MAX) NOT NULL,\n"
            f"    CONSTRAINT {_quote(pk)} PRIMARY KEY ([item_id])\n"
            f");"
        )
        return RemediationPlan(
            title="Crear estructura relacionada para valores atómicos",
            table=finding.table,
            sql=sql,
            risks=(
                "El script crea la estructura destino, pero no divide ni migra valores existentes.",
                "Debe definirse el delimitador y la clave de relación antes de migrar datos.",
                "Las aplicaciones consumidoras deberán adaptarse a la nueva relación.",
            ),
            executable=False,
        )

    if finding.rule == "2FN":
        return RemediationPlan(
            title="Descomponer dependencia parcial",
            table=finding.table,
            sql=(
                f"-- Revisión manual requerida para {qualified}.\n"
                "-- Defina la entidad destino, su clave y la estrategia de migración antes de ejecutar DDL."
            ),
            risks=(
                "La dependencia funcional no puede inferirse con certeza únicamente desde metadatos.",
                "Mover columnas automáticamente podría provocar pérdida o duplicación de información.",
                "Valide la regla de negocio y prepare un plan de migración antes de continuar.",
            ),
            executable=False,
        )

    return RemediationPlan(
        title="Revisión estructural asistida",
        table=finding.table,
        sql=f"-- Revise manualmente el hallazgo en {qualified}.\n-- {finding.recommendation}",
        risks=(
            "No existe una transformación automática segura para este hallazgo.",
            "Valide tipos de datos, dependencias y consumidores antes de definir el cambio.",
        ),
        executable=False,
    )


def wrap_transaction(sql: str, *, rollback_only: bool = False) -> str:
    return (
        "SET XACT_ABORT ON;\n"
        "SET NOCOUNT ON;\nSET LOCK_TIMEOUT 5000;\n"
        "BEGIN TRY\n"
        "    BEGIN TRANSACTION;\n\n"
        f"{_indent(sql, 4)}\n\n"
        f"    {'ROLLBACK' if rollback_only else 'COMMIT'} TRANSACTION;\n"
        "END TRY\n"
        "BEGIN CATCH\n"
        "    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;\n"
        "    THROW;\n"
        "END CATCH;"
    )


def _split_table(value: str) -> tuple[str, str]:
    parts = value.split(".", 1)
    if len(parts) == 2:
        return _identifier(parts[0]), _identifier(parts[1])
    return "dbo", _identifier(parts[0])


def _extract_quoted_name(message: str) -> str | None:
    match = re.search(r"'([^']+)'", message)
    return _identifier(match.group(1)) if match else None


def _extract_repeated_columns(message: str) -> tuple[str, ...]:
    match = re.search(r"columnas repetitivas:\s*([^.]*)", message, flags=re.IGNORECASE)
    if not match:
        return ()
    names = tuple(_identifier(value.strip()) for value in match.group(1).split(",") if value.strip())
    return names if len(names) > 1 else ()


def _build_repeated_columns_plan(
    finding: Finding,
    schema: str,
    table: str,
    qualified: str,
    repeated_columns: tuple[str, ...],
    table_metadata: TableMetadata | None,
) -> RemediationPlan:
    if table_metadata is None or len(table_metadata.primary_key_columns) != 1:
        return RemediationPlan(
            title="Normalizar columnas repetitivas",
            table=finding.table,
            sql=(
                f"-- Se detectaron las columnas: {', '.join(repeated_columns)}.\n"
                "-- Se requiere una clave primaria simple para relacionar y migrar los valores."
            ),
            risks=(
                "No se encontró una clave primaria simple para vincular los registros migrados.",
                "Crear una tabla sin relación verificable podría producir registros huérfanos.",
            ),
            executable=False,
        )

    metadata_names = {column.name.lower(): column for column in table_metadata.columns}
    if any(name.lower() not in metadata_names for name in repeated_columns):
        return RemediationPlan(
            title="Normalizar columnas repetitivas",
            table=finding.table,
            sql="-- Los metadatos cambiaron. Actualice las tablas y ejecute un nuevo diagnóstico.",
            risks=("Una o más columnas analizadas ya no existen.",),
            executable=False,
        )

    source_pk = table_metadata.primary_key_columns[0]
    if source_pk.data_type.lower() not in {"tinyint","smallint","int","bigint"}:
        return RemediationPlan("Normalizar columnas repetitivas",finding.table,
            "-- El plan por lotes requiere una clave primaria entera simple.",
            ("Este tipo de clave requiere diseño y pruebas adicionales.",),executable=False)
    prefix_match = re.match(r"(.+?)\d+$", repeated_columns[0])
    prefix = prefix_match.group(1) if prefix_match else repeated_columns[0]
    child = _safe_name(f"{table}_{prefix}_Item", 120)
    child_qualified = f"{_quote(schema)}.{_quote(child)}"
    pk_constraint = _safe_name(f"PK_{child}", 120)
    fk_constraint = _safe_name(f"FK_{child}_{table}", 120)
    values = ",\n".join(
        f"        (N'{name}', CONVERT(NVARCHAR(MAX), src.{_quote(name)}))"
        for name in repeated_columns
    )
    drop_columns = ", ".join(_quote(name) for name in repeated_columns)
    sql = (
        f"IF OBJECT_ID(N'{schema}.{child}', N'U') IS NOT NULL\n"
        f"    THROW 50001, 'La tabla destino {schema}.{child} ya existe.', 1;\n\n"
        f"CREATE TABLE {child_qualified} (\n"
        f"    [item_id] BIGINT IDENTITY(1,1) NOT NULL,\n"
        f"    [source_key] {_column_sql_type(source_pk)} NOT NULL,\n"
        f"    [attribute_name] SYSNAME NOT NULL,\n"
        f"    [value] NVARCHAR(MAX) NOT NULL,\n"
        f"    CONSTRAINT {_quote(pk_constraint)} PRIMARY KEY ([item_id]),\n"
        f"    CONSTRAINT {_quote(fk_constraint)} FOREIGN KEY ([source_key])\n"
        f"        REFERENCES {qualified} ({_quote(source_pk.name)})\n"
        f");\n\n"
        f"DECLARE @expected BIGINT, @last {_column_sql_type(source_pk)} = NULL;\n"
        f"DECLARE @batch TABLE ([source_key] {_column_sql_type(source_pk)} PRIMARY KEY);\n"
        f"SELECT @expected = SUM(CONVERT(BIGINT, "
        + " + ".join(f"CASE WHEN {_quote(n)} IS NULL THEN 0 ELSE 1 END" for n in repeated_columns)
        + f")) FROM {qualified} WITH (TABLOCKX, HOLDLOCK);\n"
        f"WHILE 1=1\nBEGIN\n"
        f"    DELETE FROM @batch;\n"
        f"    INSERT INTO @batch SELECT TOP (250) {_quote(source_pk.name)} FROM {qualified}\n"
        f"    WHERE @last IS NULL OR {_quote(source_pk.name)}>@last ORDER BY {_quote(source_pk.name)};\n"
        f"    IF @@ROWCOUNT=0 BREAK;\n"
        f"INSERT INTO {child_qualified} ([source_key], [attribute_name], [value])\n"
        f"SELECT src.{_quote(source_pk.name)}, moved.[attribute_name], moved.[value]\n"
        f"FROM {qualified} AS src\n"
        f"JOIN @batch AS b ON b.[source_key]=src.{_quote(source_pk.name)}\n"
        f"CROSS APPLY (VALUES\n{values}\n"
        f") AS moved ([attribute_name], [value])\n"
        f"WHERE moved.[value] IS NOT NULL;\n"
        f"    SELECT @last=MAX([source_key]) FROM @batch;\nEND;\n"
        f"IF (SELECT COUNT_BIG(*) FROM {child_qualified}) <> COALESCE(@expected,0)\n"
        f"    THROW 50002, 'La validación de filas migradas falló.', 1;\n\n"
        f"ALTER TABLE {qualified} DROP COLUMN {drop_columns};"
    )
    return RemediationPlan(
        title="Normalizar columnas repetitivas",
        table=finding.table,
        sql=sql,
        risks=(
            f"Se migrarán los datos de {len(repeated_columns)} columnas y después se eliminarán del origen.",
            "Constraints o código que referencien esas columnas pueden impedir el DROP COLUMN.",
            "Las aplicaciones consumidoras deberán leer los valores desde la nueva tabla relacionada.",
            "Los lotes comparten una transacción; los bloqueos y el log pueden retenerse hasta el cierre.",
        ),
        finding=finding,
    )


def _column_sql_type(column: Column) -> str:
    data_type = column.data_type.upper()
    if data_type in {"VARCHAR", "CHAR", "VARBINARY", "BINARY"}:
        length = "MAX" if column.max_length in (-1, None) else str(column.max_length)
        return f"{data_type}({length})"
    if data_type in {"NVARCHAR", "NCHAR"}:
        length = "MAX" if column.max_length in (-1, None) else str(max(1, column.max_length // 2))
        return f"{data_type}({length})"
    if data_type in {"DECIMAL", "NUMERIC"}:
        return f"{data_type}({column.precision or 38}, {column.scale if column.scale is not None else 10})"
    return data_type


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",value):
        raise ValueError("El generador DDL admite identificadores ASCII simples; este objeto requiere revisión manual.")
    return value


def _safe_name(value: str, limit: int) -> str:
    return _identifier(value[:limit])


def _quote(value: str) -> str:
    return f"[{value.replace(']', ']]')}]"


def _indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in value.splitlines())

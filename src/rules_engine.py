"""Reglas trazables: los patrones de datos son indicios, no reglas del negocio."""
import re
import statistics
import unicodedata
from collections import defaultdict
from itertools import combinations

from src.models import AuditResult, Finding, TableMetadata

MULTIVALUE_PATTERN = re.compile(
    r"^([A-Za-z0-9áéíóúÁÉÍÓÚñÑüÜ_\-]+\s*[\,;\|/\-]\s*)+"
    r"[A-Za-z0-9áéíóúÁÉÍÓÚñÑüÜ_\-]+$"
)
TEXT_TYPES = {"varchar", "nvarchar", "char", "nchar", "text", "ntext"}


def multivalue_profile(values) -> dict:
    texts = [unicodedata.normalize("NFC", str(v)) for v in values if v is not None]
    if len(texts) < 2:
        return {"status": "Indeterminado", "n": len(texts), "flag": False}
    lengths = [len(v) for v in texts]
    mean = statistics.mean(lengths)
    sd = statistics.stdev(lengths)
    matches = [bool(MULTIVALUE_PATTERN.fullmatch(v)) for v in texts]
    prevalence = sum(matches) / len(texts)
    outliers = sum(m and length > mean + sd for m, length in zip(matches, lengths))
    return {"status": "Evaluado", "n": len(texts), "regex_matches": sum(matches),
            "prevalence": prevalence, "mean_length": mean, "sd_length": sd,
            "long_matches": outliers, "flag": prevalence > .80 and outliers > 0}


def analyze_database(database: str, tables: list[TableMetadata]) -> AuditResult:
    findings = []
    for table in tables:
        findings.extend(_validate_first_normal_form(table))
        findings.extend(_validate_second_normal_form(table))
    return AuditResult(database, len(tables), tuple(findings))


def _validate_first_normal_form(table: TableMetadata) -> list[Finding]:
    findings = []
    if not table.primary_key_columns:
        findings.append(Finding(table.full_name, "Diseño", "Media",
            "La tabla no tiene una clave primaria definida.",
            "Revisar claves candidatas y definir la identificación de filas.",
            "Catálogo de claves primarias.", "Advertencia"))
    groups = defaultdict(list)
    for column in table.columns:
        match = re.fullmatch(r"(.+?)(\d+)", column.name.lower())
        if match:
            groups[match.group(1)].append(column.name)
        if column.data_type.lower() not in TEXT_TYPES:
            continue
        profile = multivalue_profile(row.get(column.name) for row in table.sample_rows)
        if profile["flag"]:
            evidence = (f"n no nulos={profile['n']}; coincidencias={profile['regex_matches']}; "
                f"proporción={profile['prevalence']:.3f}; media={profile['mean_length']:.2f}; "
                f"s={profile['sd_length']:.2f}; valores largos coincidentes={profile['long_matches']}.")
            findings.append(Finding(table.full_name, "1FN", "Alta",
                f"La columna '{column.name}' presenta indicio multivalor en datos muestreados.",
                "Confirmar el dominio y el delimitador antes de separar los valores.", evidence))
    for prefix, names in groups.items():
        if len(names) > 1:
            findings.append(Finding(table.full_name, "1FN", "Media",
                f"Se detectaron columnas repetitivas: {', '.join(names)}.",
                f"Validar el grupo '{prefix}' y revisar su relación con la clave.",
                "Patrón de nombres numerados; requiere confirmación semántica."))
    if table.profile_error:
        findings.append(Finding(table.full_name, "Cobertura", "Media",
            "El perfilado de datos no pudo completarse.",
            "Revisar permisos SELECT y tipos de datos antes de concluir el diagnóstico.",
            table.profile_error, "Indeterminado"))
    return findings


def _token(value):
    return (type(value).__name__, str(value))


def _validate_second_normal_form(table: TableMetadata) -> list[Finding]:
    keys = table.candidate_keys or ((tuple(c.name for c in table.primary_key_columns),)
                                 if table.primary_key_columns else ())
    composite = [key for key in keys if 2 <= len(key) <= 4]
    if any(len(key)>4 for key in keys):
        return [Finding(table.full_name,"Cobertura","Media",
            "Una clave compuesta excede el límite de cuatro atributos del motor.",
            "Revisar dependencias mediante análisis específico; no se certifica 2FN.",
            "Búsqueda combinatoria acotada.","Indeterminado")]
    if composite and len(table.sample_rows)<2:
        return [Finding(table.full_name,"Cobertura","Media",
            "Muestra insuficiente para evaluar dependencias parciales.",
            "Revisar datos disponibles y reglas del dominio.","Menos de dos filas.","Indeterminado")]
    if not composite:
        return []
    prime = {name for key in keys for name in key}
    findings = []
    seen = set()
    for key in composite:
        for size in range(1, len(key)):
            for determinant in combinations(key, size):
                for column in table.columns:
                    if column.name in prime:
                        continue
                    pair = (determinant, column.name)
                    if pair in seen:
                        continue
                    groups, fullkeys = defaultdict(set), defaultdict(set)
                    used = 0
                    for row in table.sample_rows:
                        if any(row.get(n) is None for n in (*key, column.name)):
                            continue
                        x = tuple(_token(row[n]) for n in determinant)
                        groups[x].add(_token(row[column.name]))
                        fullkeys[x].add(tuple(_token(row[n]) for n in key))
                        used += 1
                    repeated = sum(len(v) > 1 for v in fullkeys.values())
                    if len(groups) >= 2 and repeated >= 2 and all(len(v) == 1 for v in groups.values()):
                        seen.add(pair)
                        dep = ', '.join(determinant)
                        findings.append(Finding(table.full_name, "2FN", "Alta",
                            f"Indicio de dependencia parcial: ({dep}) → '{column.name}'.",
                            "Confirmar la dependencia en el dominio y revisar todas las claves candidatas; "
                            "la coincidencia muestral no acredita una regla universal.",
                            f"Clave=({', '.join(key)}); filas válidas={used}; grupos={len(groups)}; "
                            f"grupos con claves completas distintas={repeated}."))
    return findings

from dataclasses import dataclass, field
from typing import Iterable, Any


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool = True
    max_length: int | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references_table: str | None = None
    references_column: str | None = None
    precision: int | None = None
    scale: int | None = None


@dataclass(frozen=True)
class TableMetadata:
    schema: str
    name: str
    columns: tuple[Column, ...] = field(default_factory=tuple)
    candidate_keys: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    sample_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple, repr=False)
    sample_complete: bool = False
    profile_error: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def primary_key_columns(self) -> tuple[Column, ...]:
        return tuple(column for column in self.columns if column.is_primary_key)

    @property
    def non_key_columns(self) -> tuple[Column, ...]:
        return tuple(column for column in self.columns if not column.is_primary_key)


@dataclass(frozen=True)
class Finding:
    table: str
    rule: str
    severity: str
    message: str
    recommendation: str
    evidence: str = ""
    status: str = "Indicio"


@dataclass(frozen=True)
class AuditResult:
    database: str
    tables_analyzed: int
    findings: tuple[Finding, ...]

    @property
    def score(self) -> int:
        penalty = 0
        for finding in self.findings:
            penalty += {"Alta": 18, "Media": 10, "Baja": 5}.get(finding.severity, 5)
        return max(0, 100 - penalty)

    @property
    def high_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "Alta")

    @property
    def medium_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "Media")

    @property
    def low_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "Baja")

    @property
    def status(self) -> str:
        if self.score >= 85:
            return "Cumplimiento alto"
        if self.score >= 70:
            return "Requiere ajustes"
        return "Riesgo estructural"


def as_tuple(items: Iterable[Column]) -> tuple[Column, ...]:
    return tuple(items)


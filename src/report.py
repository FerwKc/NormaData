from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models import AuditResult, TableMetadata
from src.remediation import build_remediation_plan


INK = colors.HexColor("#0F172A")
SLATE = colors.HexColor("#475569")
LINE = colors.HexColor("#CBD5E1")
PANEL = colors.HexColor("#F8FAFC")
CYAN = colors.HexColor("#0891B2")
CYAN_LIGHT = colors.HexColor("#CFFAFE")
RED = colors.HexColor("#B91C1C")
RED_LIGHT = colors.HexColor("#FEE2E2")
AMBER = colors.HexColor("#B45309")
AMBER_LIGHT = colors.HexColor("#FEF3C7")


def export_pdf(
    result: AuditResult,
    output_path: str | Path,
    server: str = "No especificado",
    tables: list[TableMetadata] | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now()
    page_size = landscape(A4)
    document = SimpleDocTemplate(
        str(path),
        pagesize=page_size,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=30 * mm,
        bottomMargin=18 * mm,
        title=f"NORMADATA - Auditoría de {result.database}",
        author="NORMADATA Quality Studio",
        subject="Reporte de calidad estructural de base de datos",
    )
    styles = _styles()
    story = []

    story.append(Paragraph("Resumen ejecutivo", styles["section"]))
    story.append(Spacer(1, 3 * mm))
    metrics = Table(
        [
            [
                _metric("PUNTUACIÓN GENERAL", f"{result.score}/100", styles),
                _metric("ESTADO DE SALUD", result.status, styles),
                _metric("TABLAS ANALIZADAS", str(result.tables_analyzed), styles),
                _metric("HALLAZGOS", str(len(result.findings)), styles),
            ]
        ],
        colWidths=[62 * mm] * 4,
    )
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(metrics)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Hallazgos estructurales", styles["section"]))
    story.append(Paragraph(
        "Los scripts incluidos son recomendaciones técnicas. Valide dependencias, volumen de datos y copias de seguridad antes de ejecutarlos.",
        styles["caption"],
    ))
    story.append(Spacer(1, 3 * mm))

    if result.findings:
        table_data = [[
            Paragraph("SEVERIDAD", styles["th"]),
            Paragraph("REGLA", styles["th"]),
            Paragraph("TABLA AFECTADA", styles["th"]),
            Paragraph("DESCRIPCIÓN DEL PROBLEMA", styles["th"]),
            Paragraph("SCRIPT SQL SUGERIDO", styles["th"]),
        ]]
        metadata_by_name = {table.full_name: table for table in (tables or [])}
        for finding in result.findings:
            plan = build_remediation_plan(finding, metadata_by_name.get(finding.table))
            table_data.append([
                Paragraph(finding.severity, styles[f"severity_{finding.severity.lower()}"]),
                Paragraph(finding.rule, styles["badge"]),
                Paragraph(finding.table, styles["cell_strong"]),
                Paragraph(f"{finding.message}<br/><font color='#64748B'>{finding.recommendation}</font>", styles["cell"]),
                Paragraph(_escape_sql(plan.title+"\n"+"\n".join(plan.sql.splitlines()[:5])+"\nPlan completo al final del reporte."), styles["code"]),
            ])
        findings_table = Table(
            table_data,
            colWidths=[23 * mm, 17 * mm, 37 * mm, 82 * mm, 91 * mm],
            repeatRows=1,
        )
        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.45, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]
        for row in range(1, len(table_data)):
            table_style.append(("BACKGROUND", (0, row), (-1, row), colors.white if row % 2 else PANEL))
        findings_table.setStyle(TableStyle(table_style))
        story.append(findings_table)
    else:
        story.append(_empty_state(styles))

    if result.findings:
        story.append(PageBreak())
        story.append(Paragraph("Planes y evidencia de diagnóstico", styles["section"]))
        metadata_by_name = {table.full_name: table for table in (tables or [])}
        for finding in result.findings:
            plan = build_remediation_plan(finding, metadata_by_name.get(finding.table))
            story.append(Paragraph(_escape_sql(finding.table+" · "+finding.rule+" · "+finding.status),styles["body"]))
            if finding.evidence:story.append(Paragraph(_escape_sql(finding.evidence),styles["body"]))
            story.append(Paragraph(_escape_sql(plan.wrapped_sql),styles["code"]))
            story.append(Spacer(1,4*mm))

    story.append(Spacer(1, 8 * mm))
    story.append(KeepTogether([
        Paragraph("Alcance y limitaciones", styles["section"]),
        Paragraph(
            "NORMADATA consulta metadatos y muestras de hasta 1000 filas por tabla. La puntuación es un índice orientativo por penalizaciones, no un porcentaje certificado de normalización ni el ICO. Los indicios requieren confirmación del dominio. ApplicationIntent no sustituye los permisos SQL de solo lectura.",
            styles["body"],
        ),
    ]))

    def page_header_footer(canvas, doc) -> None:
        _draw_page_chrome(canvas, doc, generated_at, server, result.database)

    document.build(story, onFirstPage=page_header_footer, onLaterPages=page_header_footer)
    return path


def _draw_page_chrome(canvas, doc, generated_at: datetime, server: str, database: str) -> None:
    width, height = landscape(A4)
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, height - 22 * mm, width, 22 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(16 * mm, height - 12 * mm, "NORMADATA")
    canvas.setFillColor(colors.HexColor("#67E8F9"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(55 * mm, height - 12 * mm, "QUALITY STUDIO / SYSTEM AUDIT")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - 16 * mm, height - 9 * mm, f"Servidor: {server}")
    canvas.drawRightString(width - 16 * mm, height - 14 * mm, f"Base de datos: {database}")
    canvas.drawRightString(width - 16 * mm, height - 19 * mm, generated_at.strftime("%d/%m/%Y %H:%M"))
    canvas.setStrokeColor(LINE)
    canvas.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(16 * mm, 7.5 * mm, "Sello de auditoría de sistema · NORMADATA Quality Studio")
    canvas.drawRightString(width - 16 * mm, 7.5 * mm, f"Página {doc.page}")
    canvas.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=INK, spaceAfter=2),
        "caption": ParagraphStyle("Caption", parent=base["BodyText"], fontSize=8.5, leading=11, textColor=SLATE),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontSize=9, leading=13, textColor=SLATE),
        "metric_label": ParagraphStyle("MetricLabel", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=SLATE, alignment=TA_LEFT),
        "metric_value": ParagraphStyle("MetricValue", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=CYAN, alignment=TA_LEFT),
        "th": ParagraphStyle("TH", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.white),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontSize=7.4, leading=10, textColor=INK),
        "cell_strong": ParagraphStyle("CellStrong", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.4, leading=10, textColor=INK),
        "code": ParagraphStyle("Code", parent=base["Code"], fontName="Courier", fontSize=6.1, leading=8, textColor=INK),
        "badge": ParagraphStyle("Badge", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=CYAN, backColor=CYAN_LIGHT, borderPadding=3),
        "severity_alta": ParagraphStyle("High", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=RED, backColor=RED_LIGHT, borderPadding=3),
        "severity_media": ParagraphStyle("Medium", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=AMBER, backColor=AMBER_LIGHT, borderPadding=3),
        "severity_baja": ParagraphStyle("Low", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=SLATE, backColor=PANEL, borderPadding=3),
    }


def _metric(label: str, value: str, styles) -> list:
    return [Paragraph(label, styles["metric_label"]), Spacer(1, 2 * mm), Paragraph(value, styles["metric_value"])]


def _empty_state(styles) -> Table:
    table = Table([[Paragraph("Sin hallazgos detectados en las reglas evaluadas.", styles["body"]) ]], colWidths=[250 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("PADDING", (0, 0), (-1, -1), 14)]))
    return table


def _escape_sql(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

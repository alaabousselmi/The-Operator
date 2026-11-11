"""Build report.pdf from report.md:  pip install reportlab && python tools/build_report.py

Supports only what report.md uses: # and ## headings, paragraphs, "- " bullets,
| tables |, **bold** and `code`. Not part of the agent; reportlab is needed only here.
"""

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).parent.parent
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12.6, spaceAfter=3)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=10, bulletIndent=2, spaceAfter=1)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11, spaceAfter=0)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=2)
HEADING = ParagraphStyle("heading", parent=BODY, fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=5, spaceAfter=2)


def inline(text: str) -> str:
    """Markdown **bold** and `code` to reportlab markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r'<font face="Courier" size="9">\1</font>', text)


def table(rows: list[str]) -> Table:
    cells = [[Paragraph(inline(cell.strip()), CELL) for cell in row.strip().strip("|").split("|")]
             for row in rows if not set(row) <= set("|-: ")]
    result = Table(cells, hAlign="LEFT", repeatRows=1)
    result.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6eef6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return result


def build() -> None:
    story, paragraph, rows = [], [], []

    def flush():
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), BODY))
            paragraph.clear()
        if rows:
            story.extend([table(rows), Spacer(1, 4)])
            rows.clear()

    for line in (ROOT / "report.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            rows.append(line)
            continue
        if not line.strip() or line.startswith(("#", "- ")):
            flush()
        if line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), HEADING))
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), TITLE))
        elif line.startswith("- "):
            story.append(Paragraph(inline(line[2:]), BULLET, bulletText="•"))
        elif line.strip():
            paragraph.append(line.strip())
    flush()
    margin = 1.5 * cm
    SimpleDocTemplate(str(ROOT / "report.pdf"), pagesize=A4, leftMargin=margin, rightMargin=margin,
                      topMargin=1.3 * cm, bottomMargin=1.3 * cm, title="The Operator - report").build(story)


if __name__ == "__main__":
    build()
    print("report.pdf written")

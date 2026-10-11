"""One-page site scorecard as a PDF (spec §9.7), built with reportlab from the same payload as the site page."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RAG_COLORS = {"red": colors.HexColor("#dc2626"), "amber": colors.HexColor("#d97706"), "green": colors.HexColor("#16a34a"), "na": colors.HexColor("#9ca3af")}
MAX_REASONS, MAX_ISSUES = 6, 6      # keeps the scorecard on one page
FOOTER = "Scores and flags are reasons to look at the data, not conclusions about the site. Blinded data only."


def _num(v) -> str:
    return "-" if v is None else f"{v:.2f}"


def render(site: dict) -> bytes:
    """`site` is the GET /api/sites/{id} payload (plus `issues`)."""
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=8, leading=10)
    model = site.get("model") or {}
    scores = f"Rule score <b>{site['rule_score']:.0f}</b> / 100"
    if site.get("model_score") is not None:
        scores += f" &nbsp;&nbsp; Model score <b>{site['model_score']:.0f}</b> / 100 (closest pattern: {model.get('pattern_label', 'n/a')})"
    flow = [Paragraph(f"Site scorecard: {site['site_id']} {site.get('name') or ''}", st["Title"]),
            Paragraph(f"{site.get('subjects') or 0} subjects &nbsp;&nbsp; data as of {site['as_of']}", st["BodyText"]),
            Paragraph(scores, st["BodyText"]), Spacer(1, 4 * mm), Paragraph("Key risk indicators", st["Heading3"])]
    rows = [["", "Indicator", "Value", "Median across sites", "Rule"]]
    styles = [("FONTSIZE", (0, 0), (-1, -1), 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
              ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for n, (k, d) in enumerate(site["kri_defs"].items(), 1):
        c = site["kris"].get(k) or {}
        rows.append(["", d["label"], _num(c.get("value")), _num(c.get("comparator")), Paragraph(d["rule"], small)])
        styles.append(("BACKGROUND", (0, n), (0, n), RAG_COLORS[c.get("rag") or "na"]))
    flow.append(Table(rows, colWidths=[5 * mm, 62 * mm, 18 * mm, 30 * mm, 60 * mm], style=TableStyle(styles)))
    flow += [Spacer(1, 4 * mm), Paragraph("Reasons to look", st["Heading3"])]
    reasons = site.get("explanations") or []
    flow += [Paragraph(f"- {e['text']}", small) for e in reasons[:MAX_REASONS]] or [Paragraph("Nothing stands out against the rest of the study.", small)]
    if len(reasons) > MAX_REASONS:
        flow.append(Paragraph(f"...and {len(reasons) - MAX_REASONS} more on the site page.", small))
    issues = [i for i in site.get("issues") or [] if i["status"] != "closed"]
    flow += [Spacer(1, 4 * mm), Paragraph(f"Open issues ({len(issues)})", st["Heading3"])]
    flow += [Paragraph(f"- {i['title']} (opened {i['opened']}, owner {i['owner'] or 'unassigned'})", small) for i in issues[:MAX_ISSUES]] or [Paragraph("None.", small)]
    flow += [Spacer(1, 6 * mm), Paragraph(FOOTER, small)]
    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                      title=f"Site {site['site_id']} scorecard").build(flow)
    return buf.getvalue()

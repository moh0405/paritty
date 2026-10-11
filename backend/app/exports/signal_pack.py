"""Signal review meeting pack (spec §9.12): flagged patients, the eDISH chart and signed notes, as a blinded PDF."""
from __future__ import annotations

import io
import math
from datetime import date

from psycopg import Connection
from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.medical.service import MedicalService

QUAD_COLOR = {"potential Hy's Law pattern": colors.HexColor("#dc2626"), "aminotransferase elevation": colors.HexColor("#f97316"),
              "bilirubin elevation": colors.HexColor("#d97706"), "within thresholds": colors.HexColor("#9ca3af")}
SUBJECT_TYPES = {"hys_law", "lab_grade4", "lab_grade3", "ae_lab_link"}


def edish_drawing(points: list[dict], w: float = 440, h: float = 300) -> Drawing:
    """Log-log scatter of peak ALT/AST against peak bilirubin (multiples of ULN) with the 3x and 2x thresholds. No treatment arm."""
    d = Drawing(w, h)
    left, bottom, right, top = 50, 40, w - 15, h - 15
    lo, hix, hiy = 0.1, 30.0, 15.0
    X = lambda v: left + (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hix) - math.log10(lo)) * (right - left)  # noqa: E731
    Y = lambda v: bottom + (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hiy) - math.log10(lo)) * (top - bottom)  # noqa: E731
    d.add(Line(left, bottom, right, bottom)); d.add(Line(left, bottom, left, top))
    d.add(Line(X(3), bottom, X(3), top, strokeColor=colors.red, strokeDashArray=[3, 2])); d.add(Line(left, Y(2), right, Y(2), strokeColor=colors.red, strokeDashArray=[3, 2]))
    for t in (0.1, 1, 10):
        d.add(String(X(t), bottom - 12, f"{t:g}", fontSize=7, textAnchor="middle"))
    for t in (0.1, 1, 10):
        d.add(String(left - 6, Y(t) - 2, f"{t:g}", fontSize=7, textAnchor="end"))
    d.add(String((left + right) / 2, 8, "peak ALT/AST (x ULN)", fontSize=8, textAnchor="middle"))
    d.add(String(8, (top + bottom) / 2, "peak bilirubin (x ULN)", fontSize=8, textAnchor="middle"))
    for p in points:
        d.add(Circle(X(p["peak_amino"]), Y(p["peak_bili"]), 3, fillColor=QUAD_COLOR.get(p["quadrant"], colors.grey), strokeColor=None))
    return d


def build_pack(conn: Connection, day: date) -> bytes:
    svc = MedicalService(conn)
    items = [i for i in svc.review_items(day) if i.type in SUBJECT_TYPES or i.type in ("site_creep", "ae_cluster")]
    edish = svc.edish()
    notes = {u: (t, st, by, at) for u, t, st, by, at in conn.execute(
        "SELECT subject_ref, body->>'text', state, approved_by, approved_at FROM ops.drafts WHERE kind = 'note' AND state <> 'rejected' ORDER BY created_at")}
    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm, title="Signal review pack")
    el = [Paragraph("Signal review pack", st["Title"]), Paragraph(f"As of simulated date {day}. Blinded: the treatment arm is not shown anywhere in this document.", st["Normal"]), Spacer(1, 10)]
    counts: dict[str, int] = {}
    for i in items:
        counts[i.type] = counts.get(i.type, 0) + 1
    labels = {"hys_law": "Potential Hy's Law patterns", "lab_grade4": "Grade 4 lab results", "lab_grade3": "Grade 3 lab results", "ae_lab_link": "Adverse events near a lab change",
              "site_creep": "Sites with rising ALT", "ae_cluster": "Rare adverse event clusters"}
    rows = [["Signal", "Count"]] + [[labels[k], str(v)] for k, v in sorted(counts.items(), key=lambda x: -x[1])] or [["Signal", "Count"], ["None", "0"]]
    t = Table(rows, colWidths=[10 * cm, 3 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    el += [t, Spacer(1, 12), Paragraph("Liver safety overview (eDISH)", st["Heading2"]),
           Paragraph("Each point is one subject: the highest ALT/AST and the highest bilirubin seen, as multiples of the upper limit of normal. Points beyond both dashed lines are "
                     "potential Hy's Law patterns and need medical review; they are reasons to look, not diagnoses.", st["Normal"]), Spacer(1, 6), edish_drawing(edish)]
    subjects = [i for i in items if i.usubjid]
    seen: set[str] = set()
    if subjects:
        el += [PageBreak(), Paragraph("Flagged patients", st["Heading2"])]
    for it in subjects:
        if it.usubjid in seen:
            continue
        seen.add(it.usubjid)
        mine = [x for x in subjects if x.usubjid == it.usubjid]
        el += [Paragraph(f"{it.usubjid} (site {it.site_id})", st["Heading3"])]
        el += [Paragraph(f"&bull; {x.title} ({x.event_day})", st["Normal"]) for x in mine]
        note = notes.get(it.usubjid)
        if note and note[1] in ("signed", "approved"):
            el += [Paragraph(f"<b>Review note</b> (signed by {note[2]}):", st["Normal"]), Paragraph(note[0] or "", st["Normal"])]
        elif note:
            el += [Paragraph(f"<b>Review note</b> (draft, not yet signed): {note[0]}", st["Normal"])]
        else:
            el += [Paragraph("<b>Review note:</b> none yet.", st["Normal"])]
        el += [Spacer(1, 8)]
    site_items = [i for i in items if not i.usubjid]
    if site_items:
        el += [Paragraph("Site-level signals", st["Heading2"])] + [Paragraph(f"&bull; {i.title}", st["Normal"]) for i in site_items]
    doc.build(el)
    return buf.getvalue()

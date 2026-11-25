"""Informe PDF nativo (reportlab). Todo el texto se escapa; solo fuentes estándar (Latin-1/WinAnsi)."""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BAND_COLORS = {"bajo": "#2e7d32", "moderado": "#a68500", "elevado": "#d9730d", "alto": "#c62828",
               "critico": "#7b1fa2", "indeterminado": "#546e7a"}
NOTE = "Informe orientativo generado automáticamente. No es una prueba pericial ni certifica la autenticidad de ningún producto."


def _t(s) -> str:
    """Escapa XML y sustituye lo que Helvetica (WinAnsi) no puede dibujar."""
    s = str(s or "").encode("cp1252", "replace").decode("cp1252")
    return escape(s)


def render_pdf(r: dict) -> bytes:
    a = r["assessment"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Informe {r['id']}", author="¿Me engañan?")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    big = ParagraphStyle("big", parent=ss["Title"], fontSize=30, leading=34, alignment=0,
                         textColor=colors.HexColor(BAND_COLORS.get(a["band"], "#333333")))

    def bullets(items):
        items = items or ["—"]
        return ListFlowable([ListItem(Paragraph(_t(i), body), leftIndent=10) for i in items], bulletType="bullet", start="•", leftIndent=12)

    score = "?" if a["score"] is None else f"{a['score']}/100"
    el = [Paragraph("Informe de análisis de riesgo", ss["Title"]),
          Paragraph(_t(f"ID {r['id']} · {r['created_at']} · tipo: {r['kind']} · motor {a['engine_version']} / reglas {a['ruleset_version']} · "
                       f"IA: {r['llm'].get('model') or 'no utilizada'}"), small),
          Spacer(1, 6), Paragraph(_t(f"{score} — {a['band_label']}"), big),
          Paragraph(_t(f"Confianza del análisis: {round(a['confidence'] * 100)} %"), body)]
    if r.get("summary"):
        el.append(Paragraph("<b>Resumen:</b> " + _t(r["summary"]), body))
    el.append(Paragraph("Señales detectadas", h2))
    if a["signals"]:
        rows = [[Paragraph("<b>Señal</b>", body), Paragraph("<b>Peso</b>", body), Paragraph("<b>Origen</b>", body), Paragraph("<b>Evidencia</b>", body)]]
        for s in a["signals"]:
            rows.append([Paragraph(_t(s["title"]), body), Paragraph(f"{s['contribution'] * 100:.0f}", body),
                         Paragraph(_t(s["source"]), body), Paragraph(_t(s["evidence"]), small)])
        t = Table(rows, colWidths=[55 * mm, 14 * mm, 22 * mm, 83 * mm], repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
        el.append(t)
    else:
        el.append(Paragraph("Sin señales detectadas.", body))
    if a["mitigators"]:
        el += [Paragraph("Factores que reducen el riesgo", h2), bullets([f"{m['title']} — {m['evidence']}" for m in a["mitigators"]])]
    el += [Paragraph("No se pudo verificar", h2), bullets(a["unverifiable"]),
           Paragraph("Recomendaciones", h2), bullets(a["recommendations"])]
    ck = r.get("checklist")
    if ck:
        el += [Paragraph(f"Guía de comprobación: {_t(ck['label'])}", h2), bullets(ck["checks"]),
               Paragraph("<b>Preguntas para el vendedor</b>", body), bullets(ck["questions"]),
               Paragraph("<b>Verificación definitiva:</b> " + _t(ck["professional"]), body)]
    el += [Paragraph("Limitaciones", h2), bullets(a["limitations"]), Spacer(1, 8), Paragraph(_t(NOTE), small)]
    doc.build(el)
    return buf.getvalue()

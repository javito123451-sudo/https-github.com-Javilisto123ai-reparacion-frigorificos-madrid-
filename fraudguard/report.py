from __future__ import annotations

from html import escape as e

LIMIT_NOTE = "Informe orientativo generado automáticamente. No es una prueba pericial ni certifica autenticidad."


def render_report(r: dict) -> str:
    a = r["assessment"]
    score = "—" if a["score"] is None else str(a["score"])
    rows = "".join(
        f"<tr><td>{e(s['title'])}</td><td>{s['contribution']*100:.0f}</td><td>{e(s['source'])}</td><td>{e(s['evidence'])}</td></tr>"
        for s in a["signals"]) or "<tr><td colspan=4>Sin señales detectadas.</td></tr>"
    li = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs) or "<li>—</li>"
    return f"""<!doctype html><html lang="es"><meta charset="utf-8"><title>Informe {e(r['id'])}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#111}}
h1{{font-size:1.4rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.4rem;text-align:left;vertical-align:top}}
.score{{font-size:2.4rem;font-weight:700}}small{{color:#555}}@media print{{a{{display:none}}}}</style>
<h1>Informe de análisis de riesgo</h1>
<p><small>ID {e(r['id'])} · {e(r['created_at'])} · tipo: {e(r['kind'])} · motor {e(a['engine_version'])} / reglas {e(a['ruleset_version'])}
· IA: {e(str(r['llm']['model'] or 'no utilizada'))}</small></p>
<p class="score">{e(score)}/100 — {e(a['band_label'])}</p>
<p>Confianza del análisis: {a['confidence']*100:.0f} %</p>
<p><b>Resumen:</b> {e(r.get('summary',''))}</p>
<h2>Señales detectadas</h2><table><tr><th>Señal</th><th>Peso</th><th>Origen</th><th>Evidencia</th></tr>{rows}</table>
<h2>Factores atenuantes</h2><ul>{li([m['title'] + ' — ' + m['evidence'] for m in a['mitigators']])}</ul>
<h2>No se pudo verificar</h2><ul>{li(a['unverifiable'])}</ul>
<h2>Recomendaciones</h2><ul>{li(a['recommendations'])}</ul>
<h2>Limitaciones</h2><ul>{li(a['limitations'])}</ul>
<p><small>{e(LIMIT_NOTE)}</small></p>
<p><small>Para guardar como PDF usa «Imprimir» del navegador.</small></p></html>"""

"""FRAUD RISK ENGINE — determinista, explicable y sin dependencias de red.

El LLM nunca decide la puntuación: solo aporta señales tipadas. Aquí se agregan.
La puntuación NO es una probabilidad de fraude.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .catalog import CATALOG, MITIGATORS, RULESET_VERSION, band_for

ENGINE_VERSION = "0.1.0"
MAX_CONTRIBUTION = 0.95
MITIGATION_FLOOR = 0.6   # los atenuantes nunca reducen más de un 40 %
GENERAL_ADVICE = "Si dudas, no pagues. Línea de ayuda en ciberseguridad de INCIBE: 017 (gratuita). Si ya has pagado, contacta con tu banco y denuncia."


class Signal(BaseModel):
    code: str
    category: str = ""
    title: str = ""
    advice: str = ""
    severity: float = 0.9       # 0..1 intensidad de la señal
    certainty: float = 0.8      # 0..1 cuán seguros estamos de que está presente
    verified: bool = False      # comprobada con una fuente objetiva (RDAP, dato aportado...)
    source: str = "rule"        # rule | llm | rule+llm | rdap | user_input | heuristic
    evidence: str = ""
    contribution: float = 0.0


class Mitigator(BaseModel):
    code: str
    title: str = ""
    certainty: float = 0.8
    reduction: float = 0.0
    source: str = "rule"
    evidence: str = ""


class Coverage(BaseModel):
    input_chars: int = 0
    images: int = 0
    llm_used: bool = False
    page_fetched: bool | None = None
    domain_age_checked: bool | None = None
    reference_price_given: bool = False


class Assessment(BaseModel):
    score: int | None
    band: str
    band_label: str
    verdict: str                    # scored | indeterminate
    confidence: float
    signals: list[Signal] = Field(default_factory=list)
    mitigators: list[Mitigator] = Field(default_factory=list)
    unverifiable: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    ruleset_version: str = RULESET_VERSION
    engine_version: str = ENGINE_VERSION


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def compute_confidence(c: Coverage) -> float:
    conf = 0.30 if c.input_chars >= 20 or c.images else 0.10
    if c.llm_used:
        conf += 0.30
    if c.page_fetched:
        conf += 0.10
    if c.domain_age_checked:
        conf += 0.15
    if c.reference_price_given:
        conf += 0.10
    return round(min(conf, 0.95), 2)


def evaluate(signals: list[Signal], mitigators: list[Mitigator], coverage: Coverage,
             unverifiable: list[str] | None = None, extra_limitations: list[str] | None = None) -> Assessment:
    unverifiable = list(unverifiable or [])
    limitations = [
        "La puntuación es un indicador de señales de riesgo, NO una probabilidad matemática de fraude.",
        "Este análisis no certifica la autenticidad de ningún producto ni la honestidad de ninguna persona o empresa.",
    ] + list(extra_limitations or [])
    if coverage.images:
        limitations.append("Una fotografía no permite certificar autenticidad: solo señalar indicios visuales. "
                           "Para confirmarla hace falta un profesional autorizado o la verificación del fabricante.")
    if not coverage.llm_used:
        limitations.append("Análisis realizado solo con reglas automáticas (sin IA): cobertura limitada.")

    clean: list[Signal] = []
    for s in signals:
        d = CATALOG.get(s.code)
        if d is None:          # guardarraíl: códigos fuera de catálogo se descartan
            continue
        s = s.model_copy(update={"category": d.category, "title": d.title, "advice": d.advice})
        s.severity, s.certainty = _clamp(s.severity), _clamp(s.certainty)
        s.contribution = round(min(MAX_CONTRIBUTION, d.weight * s.severity * s.certainty), 4)
        clean.append(s)
    clean.sort(key=lambda s: s.contribution, reverse=True)

    keep: list[Mitigator] = []
    mit_factor = 1.0
    for m in mitigators:
        d = MITIGATORS.get(m.code)
        if d is None:
            continue
        m = m.model_copy(update={"title": d[0], "reduction": d[1], "certainty": _clamp(m.certainty)})
        keep.append(m)
        mit_factor *= 1 - m.reduction * m.certainty
    mit_factor = max(MITIGATION_FLOOR, mit_factor)

    p_clear = 1.0
    for s in clean:
        p_clear *= 1 - s.contribution
    score = round(100 * (1 - p_clear) * mit_factor)
    confidence = compute_confidence(coverage)

    too_short = coverage.input_chars < 15 and not coverage.images
    if too_short:
        verdict, score_out = "indeterminate", None
        limitations.append("Hay muy poca información para evaluar.")
    elif not clean and confidence < 0.5:
        verdict, score_out = "indeterminate", None
        limitations.append("No se detectaron señales, pero con las comprobaciones disponibles no se puede descartar el riesgo.")
    elif confidence < 0.35 and score <= 20:
        verdict, score_out = "indeterminate", None
    else:
        verdict, score_out = "scored", score
    key, label = band_for(score) if score_out is not None else ("indeterminado", "Indeterminado")

    recs: list[str] = []
    for s in clean:
        if s.advice and s.advice not in recs:
            recs.append(s.advice)
    recs = recs[:6]
    if score_out is not None and score_out >= 41:
        recs.insert(0, "No pagues ni facilites datos hasta haber comprobado la oferta por una vía independiente.")
    recs.append(GENERAL_ADVICE)

    return Assessment(score=score_out, band=key, band_label=label, verdict=verdict, confidence=confidence,
                      signals=clean, mitigators=keep, unverifiable=unverifiable,
                      recommendations=recs, limitations=limitations)

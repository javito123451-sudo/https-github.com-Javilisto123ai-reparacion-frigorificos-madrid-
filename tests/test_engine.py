import re
from fraudguard.catalog import CATALOG, MITIGATORS
from fraudguard.engine import Coverage, Mitigator, Signal, evaluate

COV = Coverage(input_chars=200, llm_used=True)


def sig(code, sev=0.9, cert=0.8, **kw):
    return Signal(code=code, severity=sev, certainty=cert, **kw)


def test_no_signals_with_ai_is_low_risk():
    a = evaluate([], [], COV)
    assert a.verdict == "scored" and a.score == 0 and a.band == "bajo"


def test_no_signals_without_ai_is_indeterminate_not_safe():
    a = evaluate([], [], Coverage(input_chars=200, llm_used=False))
    assert a.verdict == "indeterminate" and a.score is None and a.band_label == "Indeterminado"


def test_too_little_input_is_indeterminate():
    assert evaluate([], [], Coverage(input_chars=5)).verdict == "indeterminate"


def test_more_signals_never_lower_the_score():
    codes = ["URGENCY_PRESSURE", "ADVANCE_PAYMENT_REQUESTED", "OFF_PLATFORM_PAYMENT", "SENSITIVE_DATA_REQUESTED"]
    prev = -1
    for n in range(len(codes) + 1):
        s = evaluate([sig(c) for c in codes[:n]], [], COV).score
        assert s >= prev
        prev = s


def test_score_bounded_and_saturates():
    a = evaluate([sig(c, 1, 1) for c in CATALOG], [], COV)
    assert 0 <= a.score <= 100 and a.band in {"alto", "critico"}


def test_mitigators_reduce_but_never_more_than_floor():
    base = evaluate([sig("ADVANCE_PAYMENT_REQUESTED", 1, 1), sig("FAKE_PAYMENT_LINK", 1, 1)], [], COV).score
    mits = [Mitigator(code=c, certainty=1) for c in MITIGATORS]
    low = evaluate([sig("ADVANCE_PAYMENT_REQUESTED", 1, 1), sig("FAKE_PAYMENT_LINK", 1, 1)], mits, COV).score
    assert low < base and low >= round(base * 0.6) - 1


def test_unknown_codes_are_dropped_guardrail():
    a = evaluate([sig("APARIENCIA_DEL_VENDEDOR"), sig("URGENCY_PRESSURE")], [], COV)
    assert [s.code for s in a.signals] == ["URGENCY_PRESSURE"]


def test_bands_boundaries():
    from fraudguard.catalog import band_for
    assert [band_for(x)[0] for x in (0, 20, 21, 40, 41, 60, 61, 80, 81, 100)] == [
        "bajo", "bajo", "moderado", "moderado", "elevado", "elevado", "alto", "alto", "critico", "critico"]


def test_catalog_has_no_personal_attribute_signals():
    banned = ("raza", "nacionalidad", "origen", "etnia", "acento", "aspecto", "apariencia", "religion", "race", "ethnic")
    for d in CATALOG.values():
        text = (d.title + " " + d.definition).lower()
        assert not any(re.search(rf"\b{b}", text) for b in banned), d.code


def test_limitations_always_present_and_score_not_probability():
    a = evaluate([sig("URGENCY_PRESSURE")], [], COV)
    assert any("NO una probabilidad" in l for l in a.limitations)


def test_images_add_authenticity_limitation():
    a = evaluate([], [], Coverage(input_chars=0, images=1, llm_used=True))
    assert any("certificar autenticidad" in l for l in a.limitations)

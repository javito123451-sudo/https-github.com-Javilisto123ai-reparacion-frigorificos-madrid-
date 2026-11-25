from eval.run import run


def test_rules_mode_regression_on_synthetic_set():
    r = run()["by_channel"]["TOTAL"]
    # Umbrales de regresión del modo reglas sobre el conjunto SINTÉTICO (no es una garantía en producción).
    assert r["fp_rate"] <= 0.05, r
    assert r["recall"] >= 0.80, r

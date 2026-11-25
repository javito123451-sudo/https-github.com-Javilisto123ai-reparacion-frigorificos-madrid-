"""Mide el modo reglas (sin IA) del Fraud Risk Engine. Positivo = puntuación >= 41 (riesgo elevado o superior)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from fraudguard import rules
from fraudguard.engine import Coverage, evaluate

CASES = Path(__file__).with_name("cases.jsonl")
THRESHOLD = 41


def predict(text: str) -> tuple[bool, int | None]:
    sigs, mits = rules.detect_text(text)
    psigs, _ = rules.detect_price(rules.extract_price(text), None, text)
    sigs += psigs
    a = evaluate(sigs, mits, Coverage(input_chars=len(text), llm_used=False))
    # sin IA, "indeterminado" = no se afirma riesgo
    return (a.score is not None and a.score >= THRESHOLD), a.score


def run() -> dict:
    stats = defaultdict(lambda: dict(tp=0, fp=0, tn=0, fn=0))
    misses = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        pos, score = predict(c["text"])
        key = "tp" if pos and c["label"] == "fraud" else "fp" if pos else "fn" if c["label"] == "fraud" else "tn"
        for k in (c["channel"], "TOTAL"):
            stats[k][key] += 1
        if key in ("fp", "fn"):
            misses.append((key, c["id"], score))
    out = {}
    for k, s in stats.items():
        P, N = s["tp"] + s["fn"], s["fp"] + s["tn"]
        out[k] = {**s, "recall": s["tp"] / P if P else None, "fp_rate": s["fp"] / N if N else None}
    return {"by_channel": out, "misses": misses}


if __name__ == "__main__":
    r = run()
    for k, v in sorted(r["by_channel"].items()):
        rc = "n/a" if v["recall"] is None else f"{v['recall']:.0%}"
        fp = "n/a" if v["fp_rate"] is None else f"{v['fp_rate']:.0%}"
        print(f"{k:12} TP={v['tp']:2} FN={v['fn']:2} FP={v['fp']:2} TN={v['tn']:2}  recall={rc:>5} FP-rate={fp:>5}")
    print("fallos:", r["misses"])

"""Evalúa el pipeline COMPLETO (reglas + IA real) sobre eval/cases.jsonl. Gasta llamadas reales a la API."""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fraudguard.config import Settings
from fraudguard.llm import make_default_provider
from fraudguard.service import AnalysisService, Context
from fraudguard.store import Store

THRESHOLD = 41
CASES = Path(__file__).with_name("cases.jsonl")


def main():
    s = Settings(db_path=":memory:", rate_per_hour=10**6, daily_llm_calls=10**6)
    prov = make_default_provider(s.model)
    assert prov, "Falta OPENAI_API_KEY"
    svc = AnalysisService(s, Store(":memory:"), prov)
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines()]

    def one(ic):
        i, c = ic
        ctx = Context(channel="presencial" if c["channel"] == "presencial" else None)
        r = svc.analyze_text(f"eval{i}", c["text"], ctx, plan="premium")
        return c, r

    with ThreadPoolExecutor(6) as ex:
        out = list(ex.map(one, enumerate(cases)))
    st = defaultdict(lambda: dict(tp=0, fp=0, tn=0, fn=0)); misses = []; used = 0
    for c, r in out:
        a = r["assessment"]; used += r["llm"]["used"]
        pos = a["score"] is not None and a["score"] >= THRESHOLD
        k = "tp" if pos and c["label"] == "fraud" else "fp" if pos else "fn" if c["label"] == "fraud" else "tn"
        st["TOTAL"][k] += 1
        if k in ("fp", "fn"):
            misses.append((k, c["id"], a["score"], [x["code"] for x in a["signals"]], c["text"][:70]))
    t = st["TOTAL"]; P, N = t["tp"] + t["fn"], t["fp"] + t["tn"]
    print(f"IA usada en {used}/{len(out)} casos | TP={t['tp']} FN={t['fn']} FP={t['fp']} TN={t['tn']} | recall={t['tp']/P:.0%} FP-rate={t['fp']/N:.0%}")
    for m in misses: print(" ", m)


if __name__ == "__main__":
    main()

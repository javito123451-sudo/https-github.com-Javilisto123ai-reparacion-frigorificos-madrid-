"""Orquestación: reglas + verificaciones objetivas + IA → señales → Fraud Risk Engine → expediente."""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field

from . import checklists, rules
from .auth import PLANS
from .catalog import CATALOG, MITIGATORS
from .config import Settings
from .engine import Coverage, Mitigator, Signal, evaluate
from .imaging import BadImage, sanitize_image
from .llm import Extraction, LLMError, LLMProvider, LLMRefusal
from urllib.parse import urlsplit

from .netsafe import UnresolvableURL, UnsafeURL, extract_page, safe_fetch, validate_public_url
from .store import Store, now_utc

CHANNELS = {"wallapop", "vinted", "marketplace", "milanuncios", "web", "email", "sms", "whatsapp", "presencial", "otro"}


class Context(BaseModel):
    price_eur: float | None = Field(default=None, ge=0, le=10_000_000)
    reference_price_eur: float | None = Field(default=None, ge=0, le=10_000_000)
    brand_claimed: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=30)
    channel: str | None = None
    situation: str | None = Field(default=None, max_length=2000)

    def clean_channel(self) -> str | None:
        return self.channel if self.channel in CHANNELS else None


class QuotaExceeded(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, limit: int, window: int = 3600):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise RateLimited(int(self.window - (now - q[0])) + 1)
            q.append(now)


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", rules.fold(s)).strip()


def _rdap_age_days(domain: str, fetch: Callable, settings: Settings) -> int | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,250}\.[a-z0-9-]{2,63}", domain):
        return None
    import json
    r = fetch(f"https://rdap.org/domain/{domain}", accept_types=("application/rdap+json", "application/json", "text/plain"),
              max_bytes=300_000, allow_private=settings.allow_private_fetch, trust_env=settings.fetch_trust_env)
    if r.status != 200:
        return None
    data = json.loads(r.text)
    for ev in data.get("events", []):
        if ev.get("eventAction") == "registration":
            d = datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return max(0, (now_utc() - d).days)
    return None


class AnalysisService:
    def __init__(self, settings: Settings, store: Store, provider: LLMProvider | None,
                 fetch: Callable = safe_fetch):
        self.s, self.store, self.provider, self.fetch = settings, store, provider, fetch
        self.limiter = RateLimiter(settings.rate_per_hour)
        self._budget_day, self._budget_n = date.today(), 0
        self._blk = threading.Lock()

    # ------------------------------------------------------------ utilidades
    def check_rate(self, key: str) -> None:
        self.limiter.check(key)

    def check_quota(self, owner: str, plan: str, image: bool) -> None:
        lim = PLANS.get(plan, PLANS["free"])
        u = self.store.usage(owner)
        if u["total"] >= lim["analyses_month"]:
            raise QuotaExceeded(f"Has agotado los {lim['analyses_month']} análisis mensuales de tu plan ({lim['label']}).")
        if image and u["images"] >= lim["images_month"]:
            raise QuotaExceeded(f"Has agotado los {lim['images_month']} análisis con imágenes de tu plan ({lim['label']}).")

    def _llm_budget_ok(self) -> bool:
        with self._blk:
            if self._budget_day != date.today():
                self._budget_day, self._budget_n = date.today(), 0
            if self._budget_n >= self.s.daily_llm_calls:
                return False
            self._budget_n += 1
            return True

    def _run_llm(self, kind: str, text: str, images: list, ctx: Context, notes: list[str]) -> Extraction | None:
        if self.provider is None:
            return None
        if not self._llm_budget_ok():
            notes.append("Se alcanzó el presupuesto diario de IA: análisis solo con reglas.")
            return None
        try:
            return self.provider.extract(kind=kind, text=text, images=images,
                                         context=ctx.model_dump(exclude_none=True))
        except LLMRefusal:
            notes.append("La IA se negó a analizar este contenido; resultado solo con reglas.")
        except LLMError as e:
            notes.append(f"La IA no estuvo disponible ({e}); resultado solo con reglas.")
        except Exception:
            notes.append("Error inesperado al consultar la IA; resultado solo con reglas.")
        return None

    @staticmethod
    def _merge(rule_sigs: list[Signal], rule_mits: list[Mitigator], ext: Extraction | None, source_text: str,
               has_images: bool) -> tuple[list[Signal], list[Mitigator], list[str]]:
        sigs: dict[str, Signal] = {s.code: s for s in rule_sigs}
        mits: dict[str, Mitigator] = {m.code: m for m in rule_mits}
        unverifiable: list[str] = []
        if ext is None:
            return list(sigs.values()), list(mits.values()), unverifiable
        hay = _squash(source_text)

        def grounded(evidence: str) -> bool:
            e = _squash(evidence)
            return bool(e) and e in hay

        for ls in ext.signals:
            d = CATALOG.get(ls.code)
            if d is None:
                continue
            cert = max(0.0, min(1.0, ls.certainty))
            sev = max(0.0, min(1.0, ls.severity))
            ev = ls.evidence.strip()[:200]
            if ls.code == "PRICE_FAR_BELOW_REFERENCE":
                continue                      # lo calcula el sistema
            if ls.code == "VISUAL_INCONSISTENCY":
                cert = min(cert, 0.6)
            elif not has_images or hay:
                if not grounded(ev):          # la cita no está en el texto: posible alucinación
                    cert *= 0.5
                    ev = f"(cita no localizada en el texto) {ev}"
            if ls.code in sigs:
                old = sigs[ls.code]
                sigs[ls.code] = old.model_copy(update={"source": "rule+llm", "certainty": min(1.0, max(old.certainty, cert) + 0.1),
                                                       "severity": max(old.severity, sev)})
            else:
                sigs[ls.code] = Signal(code=ls.code, severity=sev, certainty=cert, source="llm", evidence=ev)
        for lm in ext.mitigators:
            if lm.code in MITIGATORS and lm.code not in mits and grounded(lm.evidence):
                mits[lm.code] = Mitigator(code=lm.code, certainty=min(0.8, max(0.0, lm.certainty)), source="llm",
                                          evidence=lm.evidence.strip()[:200])
        unverifiable.extend(u.strip()[:200] for u in ext.unverifiable[:8] if u.strip())
        return list(sigs.values()), list(mits.values()), unverifiable

    def _finish(self, owner: str, kind: str, ctx: Context, sigs, mits, unv, cov: Coverage, summary: str,
                notes: list[str], meta: dict, cat_text: str = "") -> dict:
        a = evaluate(sigs, mits, cov, unv, notes)
        created = now_utc()
        result = {
            "id": uuid.uuid4().hex[:16], "kind": kind, "created_at": created.isoformat(),
            "summary": summary[:400], "context": ctx.model_dump(exclude_none=True),
            "llm": {"used": cov.llm_used, "model": getattr(self.provider, "model", None) if cov.llm_used else None},
            "meta": meta, "assessment": a.model_dump(),
        }
        cat = checklists.detect_category(ctx.category, ctx.brand_claimed, cat_text)
        if kind in ("image", "product") or ctx.channel == "presencial" or ctx.category:
            result["checklist"] = checklists.checklist_for(cat)
        self.store.save(owner, result, self.s.retention_days)
        self.store.add_usage(owner, image=kind in ("image", "product"))
        return result

    def _price(self, ctx: Context, ext: Extraction | None, text: str):
        price = ctx.price_eur if ctx.price_eur is not None else (ext.price_eur if ext and ext.price_eur is not None else rules.extract_price(text))
        brand = " ".join(filter(None, [ctx.brand_claimed, ext.detected_brand if ext else None, text[:500]]))
        sigs, unv = rules.detect_price(price, ctx.reference_price_eur, brand)
        return sigs, unv

    # ------------------------------------------------------------ análisis
    def analyze_text(self, owner: str, text: str, ctx: Context, kind: str = "text", plan: str = "free") -> dict:
        self.check_quota(owner, plan, False)
        text = text.strip()
        full = text + ("\n[Situación descrita por el usuario] " + ctx.situation if ctx.situation else "")
        notes: list[str] = []
        rsigs, rmits = rules.detect_text(full)
        ext = self._run_llm(kind, full, [], ctx, notes)
        sigs, mits, unv = self._merge(rsigs, rmits, ext, full, False)
        psigs, punv = self._price(ctx, ext, full)
        sigs += psigs
        unv += punv
        cov = Coverage(input_chars=len(full), llm_used=ext is not None, reference_price_given=bool(ctx.reference_price_eur))
        return self._finish(owner, kind, ctx, sigs, mits, unv, cov, ext.summary if ext else text[:140], notes, {}, full)

    def analyze_url(self, owner: str, url: str, ctx: Context, plan: str = "free") -> dict:
        s = self.s
        self.check_quota(owner, plan, False)
        notes: list[str] = []
        unv: list[str] = []
        try:
            t = validate_public_url(url, allow_private=s.allow_private_fetch)      # UnsafeURL → 400
            host = t.host
        except UnresolvableURL:
            if urlsplit(url.strip()).scheme not in ("http", "https"):
                raise UnsafeURL("Solo se admiten enlaces http:// o https://.")
            t, host = None, (urlsplit(url.strip()).hostname or "")
            unv.append("El dominio no se resuelve ahora mismo (puede haber sido retirado): se analiza solo la dirección, no el contenido.")
        usigs, domain = rules.detect_url(url)
        page_text, page_flags, fetched = "", "", False
        try:
            if t is None:
                raise UnresolvableURL("sin resolución")
            r = self.fetch(url, allow_private=s.allow_private_fetch, trust_env=s.fetch_trust_env)
            fetched = r.status < 400
            if fetched:
                p = extract_page(r.text)
                page_text = f"Título: {p.title}\n{p.text}"
                page_flags = (f"Formulario de contraseña: {'sí' if p.has_password_input else 'no'}; "
                              f"campos de tarjeta: {'sí' if p.has_card_input else 'no'}; "
                              f"enlaces a otros dominios: {', '.join(p.external_hosts[:10]) or 'ninguno'}")
                if r.redirects:
                    notes.append(f"La URL redirige a: {r.final_url}")
                    fsigs, _ = rules.detect_url(r.final_url)
                    have = {x.code for x in usigs}
                    usigs += [x for x in fsigs if x.code not in have]
            else:
                unv.append(f"La página respondió con estado HTTP {r.status}; no se pudo analizar su contenido.")
        except UnresolvableURL:
            pass
        except UnsafeURL as e:
            unv.append(f"No se pudo cargar la página de forma segura: {e}")
        except Exception:
            unv.append("No se pudo cargar la página (error de red o tiempo de espera).")

        mits: list[Mitigator] = []
        age_checked = None
        if domain and t is not None:
            try:
                days = _rdap_age_days(domain, self.fetch, s)
                age_checked = days is not None
                if days is None:
                    unv.append("No se pudo verificar la antigüedad del dominio (RDAP no disponible para este dominio).")
                elif days < 30:
                    usigs.append(Signal(code="DOMAIN_RECENTLY_REGISTERED", severity=1.0, certainty=1.0, verified=True, source="rdap",
                                        evidence=f"{domain} se registró hace {days} días (RDAP)."))
                elif days < 180:
                    usigs.append(Signal(code="DOMAIN_RECENTLY_REGISTERED", severity=0.5, certainty=1.0, verified=True, source="rdap",
                                        evidence=f"{domain} se registró hace {days} días (RDAP)."))
                elif days > 5 * 365:
                    mits.append(Mitigator(code="DOMAIN_ESTABLISHED", certainty=1.0, source="rdap",
                                          evidence=f"{domain} registrado hace {days // 365} años (RDAP)."))
            except Exception:
                unv.append("No se pudo consultar RDAP para verificar la antigüedad del dominio.")

        body = (f"URL: {url}\n{page_flags}\n{page_text}\n" + (f"[Situación descrita por el usuario] {ctx.situation}" if ctx.situation else ""))
        rsigs, rmits = rules.detect_text(body)
        ext = self._run_llm("url", body, [], ctx, notes)
        sigs, m2, u2 = self._merge(usigs + rsigs, rmits, ext, body, False)
        psigs, punv = self._price(ctx, ext, body)
        cov = Coverage(input_chars=len(body), llm_used=ext is not None, page_fetched=fetched,
                       domain_age_checked=age_checked, reference_price_given=bool(ctx.reference_price_eur))
        return self._finish(owner, "url", ctx, sigs + psigs, mits + m2, unv + u2 + punv, cov,
                            ext.summary if ext else f"Enlace a {host}", notes, {"host": host, "domain": domain}, body)

    def analyze_images(self, owner: str, files: list[bytes], text: str, ctx: Context, plan: str = "free") -> dict:
        self.check_quota(owner, plan, True)
        if not files:
            raise BadImage("Aporta al menos una imagen.")
        if len(files) > self.s.max_images:
            raise BadImage(f"Máximo {self.s.max_images} imágenes por análisis.")
        images = [sanitize_image(b, self.s.max_image_bytes) for b in files]
        full = (text.strip() + ("\n[Situación descrita por el usuario] " + ctx.situation if ctx.situation else "")).strip()
        notes: list[str] = []
        ext = self._run_llm("product" if ctx.channel == "presencial" or ctx.brand_claimed else "image", full, images, ctx, notes)
        rtext = full + ("\n" + ext.extracted_text if ext and ext.extracted_text else "")
        rsigs, rmits = rules.detect_text(rtext) if rtext.strip() else ([], [])
        sigs, mits, unv = self._merge(rsigs, rmits, ext, rtext, True)
        psigs, punv = self._price(ctx, ext, rtext)
        if ext is None:
            unv.append("Sin IA no se pueden examinar las imágenes: solo se han evaluado los datos escritos.")
        else:
            unv.append("La autenticidad del producto no se puede confirmar por fotografía.")
        cov = Coverage(input_chars=len(rtext), images=len(images), llm_used=ext is not None,
                       reference_price_given=bool(ctx.reference_price_eur))
        return self._finish(owner, "product" if ctx.brand_claimed else "image", ctx, sigs + psigs, mits, unv + punv, cov,
                            ext.summary if ext else "Imágenes aportadas", notes, {"images": len(images)}, rtext + " " + (ext.detected_brand or "" if ext else ""))

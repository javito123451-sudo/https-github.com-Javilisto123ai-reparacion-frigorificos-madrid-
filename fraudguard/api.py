from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .auth import DUMMY_HASH, PLANS, hash_password, normalize_email, password_problem, verify_password
from .config import Settings
from .imaging import BadImage
from .llm import LLMProvider, make_default_provider
from .netsafe import UnsafeURL
from .pdf import render_pdf
from .report import render_report
from .service import AnalysisService, Context, QuotaExceeded, RateLimited, RateLimiter
from .store import Store

STATIC = Path(__file__).parent / "static"
ANON_COOKIE, SESSION_COOKIE = "fg_owner", "fg_session"
CSP = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
CSP_REPORT = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"


class TextIn(BaseModel):
    text: str = Field(min_length=1)
    context: Context = Context()
    kind: str = "text"


class UrlIn(BaseModel):
    url: str
    context: Context = Context()


class CredsIn(BaseModel):
    email: str
    password: str


class KeyIn(BaseModel):
    label: str = Field(default="", max_length=60)


class PlanIn(BaseModel):
    plan: str


@dataclass
class Principal:
    owner: str                  # identificador de propietario de los datos
    user: dict | None = None
    plan: str = "free"
    key_id: int | None = None
    anon_token: str | None = None


def create_app(settings: Settings | None = None, provider: LLMProvider | None | str = "auto", fetch=None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    store.purge_expired()
    if provider == "auto":
        provider = make_default_provider(settings.model)
    svc = AnalysisService(settings, store, provider, **({"fetch": fetch} if fetch else {}))
    login_limiter = RateLimiter(10, 900)
    app = FastAPI(title="¿Me engañan? API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.service = svc

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):       # defensa CSRF adicional a SameSite=Lax
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if request.url.path.startswith(("/api/docs", "/api/openapi")):
            return resp
        resp.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------ identidad
    def principal(request: Request, response: Response) -> Principal:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            found = store.user_for_api_key(auth[7:].strip())
            if not found:
                raise HTTPException(401, "Clave de API no válida.", headers={"WWW-Authenticate": "Bearer"})
            u, kid = found
            return Principal(owner=f"user:{u['id']}", user=u, plan=u["plan"], key_id=kid)
        tok = request.cookies.get(SESSION_COOKIE)
        if tok:
            u = store.user_for_session(tok)
            if u:
                return Principal(owner=f"user:{u['id']}", user=u, plan=u["plan"])
        anon = request.cookies.get(ANON_COOKIE)
        if not anon or len(anon) < 32:
            anon = secrets.token_urlsafe(32)
            response.set_cookie(ANON_COOKIE, anon, httponly=True, samesite="lax", secure=settings.secure_cookies, max_age=31536000)
        return Principal(owner=anon, anon_token=anon)

    def limited(request: Request, who: Principal = Depends(principal)) -> Principal:
        ip = request.client.host if request.client else "?"
        try:
            svc.check_rate(f"k:{who.key_id}" if who.key_id else f"o:{who.owner}")
            svc.check_rate(f"ip:{ip}")
        except RateLimited as ex:
            raise HTTPException(429, "Has alcanzado el límite de análisis por hora.", headers={"Retry-After": str(ex.retry_after)})
        return who

    def need_user(who: Principal = Depends(principal)) -> Principal:
        if not who.user:
            raise HTTPException(401, "Inicia sesión para continuar.")
        return who

    def need_admin(who: Principal = Depends(need_user)) -> Principal:
        if not who.user["is_admin"]:
            raise HTTPException(403, "Solo administradores.")
        return who

    def run(fn, *a, **k):
        try:
            return fn(*a, **k)
        except QuotaExceeded as ex:
            raise HTTPException(429, str(ex))
        except UnsafeURL as ex:
            raise HTTPException(400, str(ex))
        except BadImage as ex:
            raise HTTPException(400, str(ex))

    # ------------------------------------------------------------ cuentas
    def start_session(response: Response, uid: int) -> None:
        tok = store.create_session(uid, settings.session_days)
        response.set_cookie(SESSION_COOKIE, tok, httponly=True, samesite="lax", secure=settings.secure_cookies,
                            max_age=settings.session_days * 86400)

    def merge_anonymous(request: Request, uid: int) -> None:
        anon = request.cookies.get(ANON_COOKIE)
        if anon and len(anon) >= 32:
            store.claim_anonymous(anon, f"user:{uid}")

    @app.post("/api/auth/register")
    def register(body: CredsIn, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        try:
            login_limiter.check(f"reg:{ip}")
        except RateLimited as ex:
            raise HTTPException(429, "Demasiados intentos. Inténtalo más tarde.", headers={"Retry-After": str(ex.retry_after)})
        email = normalize_email(body.email)
        if not email:
            raise HTTPException(422, "Email no válido.")
        if (p := password_problem(body.password)):
            raise HTTPException(422, p)
        uid = store.create_user(email, hash_password(body.password), is_admin=bool(settings.admin_email and email == settings.admin_email))
        if uid is None:
            raise HTTPException(409, "Ese email ya está registrado.")
        merge_anonymous(request, uid)
        start_session(response, uid)
        store.audit(f"user:{uid}", "auth.register")
        return me_payload(store.user_by_id(uid))

    @app.post("/api/auth/login")
    def login(body: CredsIn, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        email = normalize_email(body.email) or ""
        try:
            login_limiter.check(f"login:{ip}:{email}")
        except RateLimited as ex:
            raise HTTPException(429, "Demasiados intentos. Inténtalo más tarde.", headers={"Retry-After": str(ex.retry_after)})
        u = store.user_by_email(email) if email else None
        ok = verify_password(body.password, u["pw_hash"] if u else DUMMY_HASH)     # tiempo constante aprox.
        if not (u and ok) or u["disabled"]:
            store.audit(None, "auth.login_failed")
            raise HTTPException(401, "Email o contraseña incorrectos.")
        merge_anonymous(request, u["id"])
        start_session(response, u["id"])
        store.audit(f"user:{u['id']}", "auth.login")
        return me_payload(u)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        tok = request.cookies.get(SESSION_COOKIE)
        if tok:
            store.delete_session(tok)
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    def me_payload(u: dict | None, owner: str | None = None, plan: str = "free") -> dict:
        if u:
            owner, plan = f"user:{u['id']}", u["plan"]
        lim = PLANS.get(plan, PLANS["free"])
        return {"authenticated": bool(u), "email": u["email"] if u else None, "is_admin": bool(u and u["is_admin"]),
                "plan": plan, "plan_label": lim["label"], "limits": {k: lim[k] for k in ("analyses_month", "images_month")},
                "usage": store.usage(owner) if owner else {"total": 0, "images": 0}}

    @app.get("/api/me")
    def me(who: Principal = Depends(principal)):
        return me_payload(who.user, who.owner, who.plan)

    @app.get("/api/keys")
    def list_keys(who: Principal = Depends(need_user)):
        return store.list_api_keys(who.user["id"])

    @app.post("/api/keys")
    def create_key(body: KeyIn, who: Principal = Depends(need_user)):
        if who.key_id:
            raise HTTPException(403, "Crea claves desde una sesión iniciada, no con otra clave.")
        if len(store.list_api_keys(who.user["id"])) >= 10:
            raise HTTPException(409, "Máximo 10 claves activas.")
        kid, key = store.create_api_key(who.user["id"], body.label)
        store.audit(who.owner, "apikey.create", str(kid))
        return {"id": kid, "key": key, "note": "Guárdala ahora: no se volverá a mostrar."}

    @app.delete("/api/keys/{kid}")
    def revoke_key(kid: int, who: Principal = Depends(need_user)):
        if not store.revoke_api_key(who.user["id"], kid):
            raise HTTPException(404, "Clave no encontrada.")
        store.audit(who.owner, "apikey.revoke", str(kid))
        return {"revoked": kid}

    # ------------------------------------------------------------ administración
    @app.get("/api/admin/stats")
    def admin_stats(who: Principal = Depends(need_admin)):
        return {**store.stats(), "ai_connected": svc.provider is not None, "model": getattr(svc.provider, "model", None)}

    @app.get("/api/admin/users")
    def admin_users(who: Principal = Depends(need_admin)):
        return store.list_users()

    @app.put("/api/admin/users/{uid}/plan")
    def admin_set_plan(uid: int, body: PlanIn, who: Principal = Depends(need_admin)):
        if body.plan not in PLANS:
            raise HTTPException(422, "Plan desconocido.")
        if not store.set_plan(uid, body.plan):
            raise HTTPException(404, "Usuario no encontrado.")
        store.audit(who.owner, "admin.set_plan", f"{uid}:{body.plan}")
        return {"id": uid, "plan": body.plan}

    @app.put("/api/admin/users/{uid}/disabled")
    def admin_disable(uid: int, disabled: bool, who: Principal = Depends(need_admin)):
        if uid == who.user["id"]:
            raise HTTPException(409, "No puedes desactivarte a ti mismo.")
        if not store.set_disabled(uid, disabled):
            raise HTTPException(404, "Usuario no encontrado.")
        store.audit(who.owner, "admin.set_disabled", f"{uid}:{disabled}")
        return {"id": uid, "disabled": disabled}

    # ------------------------------------------------------------ análisis
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "ai_connected": svc.provider is not None,
                "provider": getattr(svc.provider, "name", None), "model": getattr(svc.provider, "model", None),
                "retention_days": settings.retention_days}

    @app.post("/api/analyze/text")
    def analyze_text(body: TextIn, who: Principal = Depends(limited)):
        if len(body.text) > settings.max_text_chars:
            raise HTTPException(413, f"Texto demasiado largo (máx. {settings.max_text_chars} caracteres).")
        return run(svc.analyze_text, who.owner, body.text, body.context,
                   kind="conversation" if body.kind == "conversation" else "text", plan=who.plan)

    @app.post("/api/analyze/url")
    def analyze_url(body: UrlIn, who: Principal = Depends(limited)):
        return run(svc.analyze_url, who.owner, body.url, body.context, plan=who.plan)

    @app.post("/api/analyze/image")
    async def analyze_image(files: list[UploadFile] = File(...), text: str = Form(""), context: str = Form("{}"),
                            who: Principal = Depends(limited)):
        try:
            ctx = Context(**json.loads(context or "{}"))
        except (ValueError, ValidationError, TypeError):
            raise HTTPException(422, "Contexto inválido.")
        if len(text) > settings.max_text_chars:
            raise HTTPException(413, "Texto demasiado largo.")
        if len(files) > settings.max_images:
            raise HTTPException(413, f"Máximo {settings.max_images} imágenes.")
        blobs = [await f.read(settings.max_image_bytes + 1) for f in files]
        return run(svc.analyze_images, who.owner, blobs, text, ctx, plan=who.plan)

    @app.get("/api/analyses")
    def list_analyses(who: Principal = Depends(principal)):
        return store.list(who.owner)

    def _get(aid: str, who: Principal) -> dict:
        r = store.get(who.owner, aid)
        if not r:
            raise HTTPException(404, "Análisis no encontrado.")
        return r

    @app.get("/api/analyses/{aid}")
    def get_analysis(aid: str, who: Principal = Depends(principal)):
        return _get(aid, who)

    @app.get("/api/analyses/{aid}/report", response_class=HTMLResponse)
    def report(aid: str, who: Principal = Depends(principal)):
        r = _get(aid, who)
        store.audit(who.owner, "report.view", aid)
        return HTMLResponse(render_report(r), headers={"Content-Security-Policy": CSP_REPORT})

    @app.get("/api/analyses/{aid}/report.pdf")
    def report_pdf(aid: str, who: Principal = Depends(principal)):
        r = _get(aid, who)
        store.audit(who.owner, "report.pdf", aid)
        return Response(render_pdf(r), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="informe-{aid}.pdf"'})

    @app.delete("/api/analyses/{aid}")
    def delete_analysis(aid: str, who: Principal = Depends(principal)):
        if not store.delete(who.owner, aid):
            raise HTTPException(404, "Análisis no encontrado.")
        return {"deleted": aid}

    @app.delete("/api/analyses")
    def delete_all(who: Principal = Depends(principal)):
        return {"deleted": store.delete_all(who.owner)}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def app_factory() -> FastAPI:  # uvicorn --factory fraudguard.api:app_factory
    return create_app()

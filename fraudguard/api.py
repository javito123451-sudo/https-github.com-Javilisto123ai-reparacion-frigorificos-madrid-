from __future__ import annotations

import json
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .config import Settings
from .imaging import BadImage
from .llm import LLMProvider, make_default_provider
from .netsafe import UnsafeURL
from .report import render_report
from .service import AnalysisService, Context, RateLimited
from .store import Store

STATIC = Path(__file__).parent / "static"
COOKIE = "fg_owner"
CSP = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


class TextIn(BaseModel):
    text: str = Field(min_length=1)
    context: Context = Context()
    kind: str = "text"


class UrlIn(BaseModel):
    url: str
    context: Context = Context()


def create_app(settings: Settings | None = None, provider: LLMProvider | None | str = "auto",
               fetch=None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    store.purge_expired()
    if provider == "auto":
        provider = make_default_provider(settings.model)
    kwargs = {"fetch": fetch} if fetch else {}
    svc = AnalysisService(settings, store, provider, **kwargs)
    app = FastAPI(title="¿Me engañan? API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.service = svc

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/docs") or request.url.path.startswith("/api/openapi"):
            return resp
        resp.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def owner(request: Request, response: Response) -> str:
        tok = request.cookies.get(COOKIE)
        if not tok or len(tok) < 32:
            tok = secrets.token_urlsafe(32)
            response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=settings.secure_cookies,
                                max_age=60 * 60 * 24 * 365)
        return tok

    def limited(request: Request, who: str = Depends(owner)) -> str:
        ip = request.client.host if request.client else "?"
        try:
            svc.check_rate(f"o:{who}")
            svc.check_rate(f"ip:{ip}")
        except RateLimited as ex:
            raise HTTPException(429, "Has alcanzado el límite de análisis por hora.", headers={"Retry-After": str(ex.retry_after)})
        return who

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "ai_connected": svc.provider is not None,
                "provider": getattr(svc.provider, "name", None), "model": getattr(svc.provider, "model", None),
                "retention_days": settings.retention_days}

    @app.post("/api/analyze/text")
    def analyze_text(body: TextIn, who: str = Depends(limited)):
        if len(body.text) > settings.max_text_chars:
            raise HTTPException(413, f"Texto demasiado largo (máx. {settings.max_text_chars} caracteres).")
        return svc.analyze_text(who, body.text, body.context, kind="conversation" if body.kind == "conversation" else "text")

    @app.post("/api/analyze/url")
    def analyze_url(body: UrlIn, who: str = Depends(limited)):
        try:
            return svc.analyze_url(who, body.url, body.context)
        except UnsafeURL as ex:
            raise HTTPException(400, str(ex))

    @app.post("/api/analyze/image")
    async def analyze_image(files: list[UploadFile] = File(...), text: str = Form(""), context: str = Form("{}"),
                            who: str = Depends(limited)):
        try:
            ctx = Context(**json.loads(context or "{}"))
        except (ValueError, ValidationError, TypeError):
            raise HTTPException(422, "Contexto inválido.")
        if len(text) > settings.max_text_chars:
            raise HTTPException(413, "Texto demasiado largo.")
        if len(files) > settings.max_images:
            raise HTTPException(413, f"Máximo {settings.max_images} imágenes.")
        blobs = []
        for f in files:
            data = await f.read(settings.max_image_bytes + 1)
            blobs.append(data)
        try:
            return svc.analyze_images(who, blobs, text, ctx)
        except BadImage as ex:
            raise HTTPException(400, str(ex))

    @app.get("/api/analyses")
    def list_analyses(who: str = Depends(owner)):
        return store.list(who)

    @app.get("/api/analyses/{aid}")
    def get_analysis(aid: str, who: str = Depends(owner)):
        r = store.get(who, aid)
        if not r:
            raise HTTPException(404, "Análisis no encontrado.")
        return r

    @app.get("/api/analyses/{aid}/report", response_class=HTMLResponse)
    def report(aid: str, who: str = Depends(owner)):
        r = store.get(who, aid)
        if not r:
            raise HTTPException(404, "Análisis no encontrado.")
        store.audit(who, "report.view", aid)
        return HTMLResponse(render_report(r), headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})

    @app.delete("/api/analyses/{aid}")
    def delete_analysis(aid: str, who: str = Depends(owner)):
        if not store.delete(who, aid):
            raise HTTPException(404, "Análisis no encontrado.")
        return {"deleted": aid}

    @app.delete("/api/analyses")
    def delete_all(who: str = Depends(owner)):
        return {"deleted": store.delete_all(who)}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def app_factory() -> FastAPI:  # uvicorn --factory fraudguard.api:app_factory
    return create_app()

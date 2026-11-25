import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from conftest import FakeProvider, png_bytes
from fraudguard.auth import hash_password, password_problem, verify_password

SCAM = "Hazme una señal de 50€ por Bizum ahora mismo, es urgente"
PW = "una-clave-larga-123"


def new_session(c):
    return TestClient(c.app)


def register(c, email="ana@example.com", pw=PW):
    return c.post("/api/auth/register", json={"email": email, "password": pw})


# ------------------------------------------------------------------ auth
def test_password_hashing():
    h = hash_password(PW)
    assert verify_password(PW, h) and not verify_password("otra", h) and PW not in h
    assert hash_password(PW) != h                       # sal aleatoria
    assert not verify_password(PW, "basura")


def test_password_policy():
    assert password_problem("corta") and password_problem("x" * 300) and password_problem(PW) is None


def test_register_login_logout_me(make_client):
    c = make_client()
    assert c.get("/api/me").json()["authenticated"] is False
    r = register(c)
    assert r.status_code == 200 and r.json()["email"] == "ana@example.com" and r.json()["plan"] == "free"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/me").json()["authenticated"] is True
    c.post("/api/auth/logout")
    assert c.get("/api/me").json()["authenticated"] is False
    assert c.post("/api/auth/login", json={"email": "ANA@example.com", "password": PW}).status_code == 200
    assert c.get("/api/me").json()["email"] == "ana@example.com"


def test_register_validation_and_duplicates(make_client):
    c = make_client()
    assert register(c, "no-es-email").status_code == 422
    assert register(c, pw="corta").status_code == 422
    assert register(c).status_code == 200
    assert register(new_session(c)).status_code == 409


def test_login_wrong_password_generic_error(make_client):
    c = make_client()
    register(c)
    s = new_session(c)
    a = s.post("/api/auth/login", json={"email": "ana@example.com", "password": "incorrecta-123"})
    b = s.post("/api/auth/login", json={"email": "nadie@example.com", "password": "incorrecta-123"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_brute_force_is_throttled(make_client):
    c = make_client()
    register(c)
    s = new_session(c)
    codes = [s.post("/api/auth/login", json={"email": "ana@example.com", "password": f"mala-clave-{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_anonymous_history_is_claimed_on_register(make_client):
    c = make_client()
    r = c.post("/api/analyze/text", json={"text": SCAM}).json()
    register(c)
    assert [x["id"] for x in c.get("/api/analyses").json()] == [r["id"]]


def test_users_cannot_see_each_others_history(make_client):
    a = make_client()
    register(a)
    r = a.post("/api/analyze/text", json={"text": SCAM}).json()
    b = new_session(a)
    register(b, "bea@example.com")
    assert b.get("/api/analyses").json() == []
    assert b.get(f"/api/analyses/{r['id']}").status_code == 404
    assert b.get(f"/api/analyses/{r['id']}/report.pdf").status_code == 404


def test_cross_origin_post_blocked(make_client):
    c = make_client()
    r = c.post("/api/analyze/text", json={"text": SCAM}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = c.post("/api/analyze/text", json={"text": SCAM}, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200


# ------------------------------------------------------------------ cuotas y planes
def test_free_quota_then_admin_upgrade(make_client):
    c = make_client(provider=None, admin_email="admin@example.com")
    adm = new_session(c)
    register(adm, "admin@example.com")
    register(c)
    for _ in range(15):
        assert c.post("/api/analyze/text", json={"text": SCAM}).status_code == 200
    r = c.post("/api/analyze/text", json={"text": SCAM})
    assert r.status_code == 429 and "mensuales" in r.json()["detail"]
    uid = c.get("/api/me").json() and next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == "ana@example.com")
    assert adm.put(f"/api/admin/users/{uid}/plan", json={"plan": "premium"}).status_code == 200
    assert c.post("/api/analyze/text", json={"text": SCAM}).status_code == 200
    m = c.get("/api/me").json()
    assert m["plan"] == "premium" and m["usage"]["total"] == 16


def test_image_quota_separate(make_client):
    c = make_client()
    register(c)
    for _ in range(5):
        assert c.post("/api/analyze/image", files=[("files", ("a.png", png_bytes(), "image/png"))]).status_code == 200
    assert c.post("/api/analyze/image", files=[("files", ("a.png", png_bytes(), "image/png"))]).status_code == 429
    assert c.post("/api/analyze/text", json={"text": SCAM}).status_code == 200


# ------------------------------------------------------------------ claves de API
def test_api_key_lifecycle(make_client):
    c = make_client()
    register(c)
    k = c.post("/api/keys", json={"label": "tienda"}).json()
    assert k["key"].startswith("fg_")
    listed = c.get("/api/keys").json()
    assert listed[0]["prefix"] == k["key"][:9] and "key" not in listed[0]
    api = TestClient(c.app)                                   # cliente sin cookies, solo Bearer
    h = {"Authorization": f"Bearer {k['key']}"}
    r = api.post("/api/analyze/text", json={"text": SCAM}, headers=h)
    assert r.status_code == 200
    assert [x["id"] for x in c.get("/api/analyses").json()] == [r.json()["id"]]   # mismo propietario que el usuario
    assert api.post("/api/keys", json={}, headers=h).status_code == 403          # una clave no crea claves
    assert c.delete(f"/api/keys/{k['id']}").status_code == 200
    assert api.post("/api/analyze/text", json={"text": SCAM}, headers=h).status_code == 401


def test_invalid_api_key_rejected_not_anonymous(make_client):
    c = make_client()
    assert c.post("/api/analyze/text", json={"text": SCAM}, headers={"Authorization": "Bearer fg_falsa"}).status_code == 401


def test_keys_require_login_and_are_isolated(make_client):
    c = make_client()
    assert c.get("/api/keys").status_code == 401
    register(c)
    k = c.post("/api/keys", json={}).json()
    other = new_session(c)
    register(other, "bea@example.com")
    assert other.get("/api/keys").json() == [] and other.delete(f"/api/keys/{k['id']}").status_code == 404


def test_api_key_not_stored_in_clear(make_client):
    c = make_client()
    register(c)
    k = c.post("/api/keys", json={}).json()["key"]
    import sqlite3
    db = sqlite3.connect(c.app.state.service.store.path)
    blob = " ".join(str(x) for row in db.execute("SELECT * FROM api_keys") for x in row)
    assert k not in blob


# ------------------------------------------------------------------ administración
def test_admin_endpoints_need_admin(make_client):
    c = make_client(admin_email="admin@example.com")
    assert c.get("/api/admin/stats").status_code == 401
    register(c, "user@example.com")
    assert c.get("/api/admin/stats").status_code == 403
    adm = new_session(c)
    register(adm, "admin@example.com")
    s = adm.get("/api/admin/stats").json()
    assert s["users"] and s["analyses_total"] == 0
    assert adm.put("/api/admin/users/999/plan", json={"plan": "premium"}).status_code == 404
    assert adm.put("/api/admin/users/1/plan", json={"plan": "inventado"}).status_code == 422


def test_admin_can_disable_user_and_kills_sessions(make_client):
    c = make_client(admin_email="admin@example.com")
    adm = new_session(c)
    register(adm, "admin@example.com")
    register(c, "user@example.com")
    uid = next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == "user@example.com")
    assert adm.put(f"/api/admin/users/{uid}/disabled", params={"disabled": "true"}).status_code == 200
    assert c.get("/api/me").json()["authenticated"] is False
    assert new_session(c).post("/api/auth/login", json={"email": "user@example.com", "password": PW}).status_code == 401
    me_id = next(u["id"] for u in adm.get("/api/admin/users").json() if u["email"] == "admin@example.com")
    assert adm.put(f"/api/admin/users/{me_id}/disabled", params={"disabled": "true"}).status_code == 409


def test_admin_stats_expose_no_content(make_client):
    c = make_client(admin_email="admin@example.com")
    register(c, "admin@example.com")
    c.post("/api/analyze/text", json={"text": SCAM})
    dump = json.dumps(c.get("/api/admin/stats").json()) + json.dumps(c.get("/api/admin/users").json())
    assert "Bizum" not in dump


# ------------------------------------------------------------------ PDF y guía de comprobación
def test_pdf_report(make_client):
    c = make_client()
    r = c.post("/api/analyze/text", json={"text": SCAM}).json()
    resp = c.get(f"/api/analyses/{r['id']}/report.pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf" and resp.content[:5] == b"%PDF-"
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)
    assert "Informe de análisis de riesgo" in text and "NO una probabilidad" in text


def test_pdf_handles_hostile_text(make_client):
    c = make_client(provider=None)
    r = c.post("/api/analyze/text", json={"text": "<b>urgente</b> &amp; <para> ✓ 日本語 señal de 10€ ahora mismo"}).json()
    assert c.get(f"/api/analyses/{r['id']}/report.pdf").status_code == 200


def test_product_checklist_for_watch_never_certifies(make_client):
    c = make_client()
    ctx = {"brand_claimed": "Rolex", "channel": "presencial", "price_eur": 100}
    r = c.post("/api/analyze/image", files=[("files", ("a.png", png_bytes(), "image/png"))], data={"context": json.dumps(ctx)}).json()
    ck = r["checklist"]
    assert ck["category"] == "reloj" and len(ck["checks"]) >= 4 and ck["questions"]
    blob = json.dumps(ck).lower()
    assert "profesional" in blob or "fabricante" in blob
    assert "es auténtico" not in blob and "es falso" not in blob


def test_checklist_category_detection_and_text_flow(make_client):
    c = make_client()
    r = c.post("/api/analyze/text", json={"text": "Me venden un iPhone 14 por la calle", "context": {"channel": "presencial"}}).json()
    assert r["checklist"]["category"] == "movil"
    plain = c.post("/api/analyze/text", json={"text": "Hola, ¿sigue disponible la mesa?"}).json()
    assert "checklist" not in plain


def test_pdf_includes_checklist(make_client):
    c = make_client()
    r = c.post("/api/analyze/image", files=[("files", ("a.png", png_bytes(), "image/png"))],
               data={"context": json.dumps({"category": "joya_oro", "channel": "presencial"})}).json()
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(f"/api/analyses/{r['id']}/report.pdf").content)).pages)
    assert "Guía de comprobación" in text and "contraste" in text.lower()

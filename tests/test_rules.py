import pytest

from fraudguard.rules import detect_price, detect_text, detect_url, registrable_domain


def codes(text):
    s, m = detect_text(text)
    return {x.code for x in s}, {x.code for x in m}


@pytest.mark.parametrize("text,expected", [
    ("Hazme una señal de 50€ para reservarlo, es urgente", {"ADVANCE_PAYMENT_REQUESTED", "URGENCY_PRESSURE"}),
    ("Te mando un enlace de pago de Correos para cobrar el dinero", {"FAKE_PAYMENT_LINK", "OFF_PLATFORM_PAYMENT"}),
    ("Pásame el código de verificación que te ha llegado por SMS", {"SENSITIVE_DATA_REQUESTED"}),
    ("Pago con tarjetas regalo de Google Play", {"PAYMENT_UNTRACEABLE"}),
    ("Rentabilidad garantizada del 5% diario sin riesgo", {"GUARANTEED_RETURNS"}),
    ("Me ha abordado un hombre por la calle ofreciéndome un reloj, solo efectivo", {"UNSOLICITED_OFFER", "CASH_IMMEDIATE_DEMAND"}),
    ("Su cuenta bancaria ha sido bloqueada, verifica tu acceso de BBVA", {"IMPERSONATION_AUTHORITY"}),
    ("No puedes probarlo ni revisarlo antes de pagar", {"SELLER_BLOCKS_INSPECTION"}),
])
def test_fraud_patterns_detected(text, expected):
    assert expected <= codes(text)[0]


@pytest.mark.parametrize("text", [
    "Vendo bicicleta de montaña, 80 euros. Puedes verla y probarla en un lugar público.",
    "Hola, ¿sigue disponible? Puedo quedar el sábado por la mañana en el centro.",
    "Lavadora Bosch 7kg, funciona perfectamente, 120€ negociables, recogida en mano.",
    "Vendo iPhone 13 con factura y caja, pago a través de la plataforma con envío protegido.",
    "Reloj Casio vintage, 35€. Tengo ticket de compra.",
    "Gracias por tu mensaje, te confirmo el pedido para el viernes.",
])
def test_legitimate_texts_raise_no_fraud_signal(text):
    assert codes(text)[0] == set()


def test_mitigators_detected():
    m = codes("Vendo con factura, pago protegido de Wallapop, puedes probarlo en un lugar público")[1]
    assert {"PROTECTED_PAYMENT_USED", "IN_PERSON_CHECK_ALLOWED", "DOCUMENTATION_PROVIDED"} <= m


def test_accent_and_case_insensitive():
    assert "ADVANCE_PAYMENT_REQUESTED" in codes("PAGO ADELANTADO OBLIGATORIO")[0]


def test_evidence_quotes_original_text():
    s, _ = detect_text("Hola. ¡Es URGENTE que me contestes hoy!")
    assert "URGENTE" in s[0].evidence


# ---- precio
def test_price_with_user_reference():
    s, _ = detect_price(100, 5000, "")
    assert s and s[0].source == "user_input" and s[0].severity == 1.0


def test_price_normal_discount_not_flagged():
    assert detect_price(700, 1000, "")[0] == []


def test_price_luxury_floor_heuristic_flagged_and_disclosed():
    s, unv = detect_price(100, None, "Reloj Rolex Submariner")
    assert s and s[0].source == "heuristic" and s[0].certainty < 0.7 and unv


def test_price_unknown_brand_unverifiable_not_flagged():
    s, unv = detect_price(5, None, "bolígrafo")
    assert s == [] and unv


def test_cheap_legit_item_not_flagged():
    assert detect_price(35, None, "Casio vintage")[0] == []


# ---- URL
@pytest.mark.parametrize("url,code", [
    ("https://wallapop-envios.com/pago", "URL_LOOKALIKE_DOMAIN"),
    ("https://www.wa11apop.com", "URL_LOOKALIKE_DOMAIN"),
    ("https://correos-seguimiento.top/x", "URL_LOOKALIKE_DOMAIN"),
    ("https://paypal.com@evil.example/login", "URL_USERINFO_TRICK"),
    ("http://192.0.2.10/login", "URL_RAW_IP"),
    ("https://bit.ly/3abc", "URL_SHORTENER"),
    ("http://tienda-ofertas.com", "URL_NO_HTTPS"),
    ("https://ofertas.xyz", "URL_SUSPICIOUS_TLD"),
])
def test_url_signals(url, code):
    assert code in {s.code for s in detect_url(url)[0]}


@pytest.mark.parametrize("url", [
    "https://www.wallapop.com/item/bici-123", "https://www.vinted.es/items/1", "https://www.amazon.es/dp/B0",
    "https://www.correos.es/es/es/herramientas/localizador", "https://example.org/",
])
def test_official_urls_clean(url):
    assert detect_url(url)[0] == []


def test_registrable_domain():
    assert registrable_domain("www.tienda.com.es") == "tienda.com.es"
    assert registrable_domain("a.b.example.com") == "example.com"


def test_extract_price_only_when_unambiguous():
    from fraudguard.rules import extract_price
    assert extract_price("Vendo reloj por 100 euros") == 100
    assert extract_price("Vendo 1.250 € negociables") == 1250
    assert extract_price("Paga 4,95€ de seguro de envío en este enlace") is None       # tasa, no precio
    assert extract_price("Hazme una señal de 50€ para reservarlo") is None
    assert extract_price("Cuesta 100€ y envío 5€") is None                              # ambiguo: dos importes
    assert extract_price("sin precio") is None


def test_shipping_fee_is_not_mistaken_for_item_price():
    s, _ = detect_text("PS5 nueva. Paga 4,95€ de seguro de envío en este enlace de Correos")
    from fraudguard.rules import extract_price
    psigs, _ = detect_price(extract_price("PS5 nueva. Paga 4,95€ de seguro de envío"), None, "PS5")
    assert psigs == []

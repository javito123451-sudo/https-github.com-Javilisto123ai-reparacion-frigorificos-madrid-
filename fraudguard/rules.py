"""Reglas deterministas (españolas) — funcionan sin IA y sin red. Alta precisión, recall limitado."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit
import ipaddress

from .engine import Mitigator, Signal


def fold(text: str) -> str:
    """minúsculas y sin acentos, preservando la longitud para poder citar el original."""
    out = []
    for ch in text.lower():
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def norm_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


_S = [
    ("ADVANCE_PAYMENT_REQUESTED", r"pago (por )?adelantado|(pago|bizum|transferencia|ingreso)\w* adelantad|adelanto de \d|(paga|pagar|ingresa|ingresar|haz|hacer|envia|enviar|dejame|deja)\w* (una |la |el )?(senal|reserva|adelanto)|senal de \d|reserva(lo|rlo)? (con|pagando|ingresando)"),
    ("PAYMENT_UNTRACEABLE", r"western union|moneygram|paysafe|tarjetas? (de )?regalo|gift ?cards?|criptomonedas?|bitcoin|usdt|google play card|itunes card"),
    ("OFF_PLATFORM_PAYMENT", r"(fuera de|sin pasar por) (wallapop|vinted|milanuncios|la plataforma|la app)|pago (directo|externo) |enlace de pago|link de pago|paga(r|me)? (por|con) (este |el )?(enlace|link)|te (mando|envio|paso) (un |el )?(enlace|link) (de pago|para pagar)"),
    ("FAKE_PAYMENT_LINK", r"(enlace|link|url).{0,60}(correos|seur|mrw|dhl|ups|wallapop|vinted|milanuncios).{0,80}(cobrar|recibir|confirmar|seguro de envio|pago)|(para|y) (cobrar|recibir) (el )?(pago|dinero)|seguro de envio.{0,40}(enlace|link|pagar)|(rellena|introduce) (los )?datos de (tu )?tarjeta.{0,40}(cobrar|recibir)"),
    ("OFF_PLATFORM_CONTACT", r"(escribeme|hablame|contactame|pasame|dame|mandame|mejor|continuemos|seguimos).{0,30}(whatsapp|telegram|signal)|(whatsapp|telegram).{0,15}(\+?\d[\d ]{6,})"),
    ("URGENCY_PRESSURE", r"urgente|urgencia|ahora mismo|ultima oportunidad|solo (hoy|por hoy)|lo antes posible|se agota|tiempo limitado|en (las )?proximas? \d+ (horas|minutos)|antes de que se (venda|agote)|hay (mas )?(gente|personas|otros?) interesad|decide ya|ya mismo"),
    ("EMOTIONAL_PRESSURE_STORY", r"necesito (el )?dinero|apuro economico|me han despedido|estoy enferm|operacion de (mi|un)|tengo (una )?deuda|por (un )?divorcio|es de (mi|un|su) (familiar|difunto|fallecido)|difunt[ao] (padre|madre|marido|esposo|abuelo|abuela)|era de mi (padre|madre|abuelo|abuela|marido|esposo)"),
    ("SENSITIVE_DATA_REQUESTED", r"(codigo|clave) (de )?(verificacion|sms|seguridad|confirmacion)|\bcvv\b|\bcvc\b|\bpin\b|contrasena|clave de (acceso|tu banco)|foto (de |del )?(tu |su )?(dni|tarjeta|pasaporte)|numero (completo )?de (tu )?(tarjeta|cuenta)|selfie con (el |tu )?dni|datos de (tu |su )?tarjeta"),
    ("IMPERSONATION_AUTHORITY", r"(banco|bbva|santander|caixabank|sabadell|hacienda|agencia tributaria|policia|guardia civil|correos|dgt|seguridad social|bizum|netflix|amazon|paypal|apple|microsoft).{0,80}(cuenta (bancaria )?(ha sido )?(bloqueada|suspendida|limitada)|cuenta de \w+ ha sido (bloqueada|suspendida|limitada)|multa pendiente|reembolso|devolucion|paquete retenido|actividad sospechosa|verifica (tu|su)|acceso no autorizado|tienes? (un )?(pago|cargo) pendiente)|(cuenta (bancaria )?(ha sido )?(bloqueada|suspendida|limitada)|paquete retenido|actividad sospechosa|acceso no autorizado|multa pendiente).{0,80}(banco|bbva|santander|caixabank|sabadell|hacienda|agencia tributaria|policia|guardia civil|correos|dgt|bizum|netflix|amazon|paypal|apple|microsoft)"),
    ("IMPERSONATION_RELATIVE", r"(mama|papa|hijo|hija|abuel[ao]|cari[no]o?).{0,80}(nuevo numero|numero nuevo|he perdido (el )?(movil|telefono)|se me (ha )?(roto|caido) el movil).{0,160}(bizum|dinero|transferencia|euros|pago|western)|(nuevo numero|numero nuevo|he perdido (el )?(movil|telefono)).{0,160}(bizum|transferencia|dinero).{0,60}(urgente|ahora|ya)"),
    ("GUARANTEED_RETURNS", r"rentabilidad garantizada|beneficios? (garantizad|seguros)|duplica(r)? (tu |su )?(dinero|inversion)|\d+ ?% (diario|semanal|al dia|a la semana)|sin riesgo.{0,30}(invers|ganar|beneficio)|ganancias? (aseguradas|garantizadas)"),
    ("UNREALISTIC_PROMISES", r"has ganado|ganador (de|del)|felicidades.{0,40}(gan|premio)|has sido seleccionad|sorteo.{0,30}(ganad|premio)|regalo gratis"),
    ("SELLER_BLOCKS_INSPECTION", r"no (puedes|se puede|podras|puedo dejar) (probar|abrir|revisar|comprobar|verificar)|no (dejo|permito|admito) (probar|revisar|comprobar|verificar)|no (te lo )?ensen[oa]|no (hay|puedo) quedar|no se (admite|permite) (revision|devolucion|prueba|visita)|no (me )?(deja|dejan|permite|permiten) (probar|revisar|comprobar|abrir|verificar)"),
    ("CASH_IMMEDIATE_DEMAND", r"(solo|unicamente) (en )?efectivo|efectivo (ya|ahora|inmediato)|dinero en efectivo (ahora|ya)|necesita (el )?dinero (ya|ahora)|pagame (ya|ahora) en efectivo"),
    ("UNSOLICITED_OFFER", r"por la calle|en la calle|me (ha )?abordado|se me (ha )?acercado|un desconocido (me )?(ofrece|ofrecio|vende)|(me )?ofrece(n)? (un |una )?(reloj|movil|iphone|joya|bolso|oro|cadena)"),
    ("NO_VERIFIABLE_DOCUMENTATION", r"sin (factura|caja|papeles|documentacion|ticket|garantia)|no tengo (la )?(factura|caja|papeles|ticket|garantia)"),
    ("AUTHENTICITY_CLAIM_UNVERIFIED", r"100 ?% (original|autentic)|totalmente (original|autentic)|garantizo que es (original|autentic)|(es )?(original|autentico) de (fabrica|tienda)|te juro que es (original|autentic)"),
]
_M = [
    ("PROTECTED_PAYMENT_USED", r"pago protegido|compra protegida|vinted go|wallapop envios|a traves de (la )?(app|plataforma)|(con|a traves de|mediante|por) (airbnb|booking|vinted|wallapop)"),
    ("IN_PERSON_CHECK_ALLOWED", r"puedes (probarlo|probarla|revisarlo|revisarla|verlo|verla|comprobarlo|comprobarla)|lugar publico|puedes venir a (verlo|verla|probarlo|probarla)|(lo|la) pruebas? (antes|en el momento)|pagas? (al|cuando) (recibir|recoger|comprobar)"),
    ("DOCUMENTATION_PROVIDED", r"con (factura|ticket|garantia|caja y papeles|certificado)|tengo (la )?(factura|ticket|garantia)|incluye (factura|garantia|caja)"),
]
_SIG_RE = [(c, re.compile(p)) for c, p in _S]
_MIT_RE = [(c, re.compile(p)) for c, p in _M]


def _snippet(original: str, start: int, end: int) -> str:
    s = max(0, start - 25)
    e = min(len(original), end + 25)
    return re.sub(r"\s+", " ", original[s:e]).strip()[:160]


def detect_text(text: str) -> tuple[list[Signal], list[Mitigator]]:
    original = re.sub(r"[ \t]+", " ", text)
    folded = fold(original)
    sigs, mits = [], []
    for code, rx in _SIG_RE:
        m = rx.search(folded)
        if m:
            sigs.append(Signal(code=code, severity=0.9, certainty=0.8, source="rule",
                               evidence=_snippet(original, m.start(), m.end())))
    for code, rx in _MIT_RE:
        m = rx.search(folded)
        if m:
            mits.append(Mitigator(code=code, certainty=0.7, source="rule",
                                  evidence=_snippet(original, m.start(), m.end())))
    return sigs, mits


# ---------------------------------------------------------------- precio (heurística orientativa)
# Umbrales internos MUY conservadores (aprox. mínimo plausible de segunda mano). NO son precios de mercado.
PRICE_FLOORS_EUR = {
    "rolex": 3000, "omega": 1200, "cartier": 1200, "breitling": 1500, "tag heuer": 500,
    "louis vuitton": 300, "gucci": 250, "chanel": 600, "prada": 250, "dior": 300, "hermes": 800,
    "iphone": 150, "playstation 5": 250, "ps5": 250, "macbook": 350,
}


def detect_price(price: float | None, reference: float | None, brand_text: str) -> tuple[list[Signal], list[str]]:
    unverifiable: list[str] = []
    if price is None:
        return [], unverifiable
    if reference and reference > 0:
        ratio = price / reference
        src, cert, ev = "user_input", 0.9, f"Precio pedido {price:g} € frente a referencia indicada por ti de {reference:g} € ({ratio:.0%})."
    else:
        b = fold(brand_text)
        floor = next((v for k, v in PRICE_FLOORS_EUR.items() if k in b), None)
        if not floor:
            unverifiable.append("No hay precio de referencia: no se puede valorar si el precio es anormal. Indica el valor de tienda para mejorar el análisis.")
            return [], unverifiable
        ratio = price / floor
        src, cert = "heuristic", 0.6
        ev = (f"Precio pedido {price:g} € frente a un umbral orientativo interno de {floor} € para esta marca "
              "(no es un precio de mercado verificado).")
        unverifiable.append("El precio se ha comparado con un umbral orientativo interno, no con precios de mercado reales.")
    if ratio >= 0.35:
        return [], unverifiable
    sev = 1.0 if ratio < 0.15 else 0.8 if ratio < 0.25 else 0.6
    return [Signal(code="PRICE_FAR_BELOW_REFERENCE", severity=sev, certainty=cert, source=src, evidence=ev,
                   verified=False)], unverifiable


# ---------------------------------------------------------------- URL
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rb.gy", "shorturl.at", "ow.ly",
              "buff.ly", "tiny.cc", "rebrand.ly", "bit.do", "lnkd.in", "t.ly", "s.id", "v.gd"}
SUSPICIOUS_TLDS = {"top", "xyz", "click", "icu", "buzz", "cyou", "rest", "cfd", "sbs", "gq", "tk", "ml", "cf", "ga",
                   "monster", "cam", "loan", "work", "zip", "mov"}
BRANDS = {
    "wallapop": {"wallapop.com"}, "vinted": {"vinted.es", "vinted.com", "vinted.fr", "vinted.de", "vinted.it", "vinted.co.uk"},
    "milanuncios": {"milanuncios.com"}, "correos": {"correos.es", "correosexpress.com"}, "seur": {"seur.com"},
    "mrw": {"mrw.es"}, "dhl": {"dhl.com", "dhl.es"}, "ups": {"ups.com"}, "bbva": {"bbva.es", "bbva.com"},
    "santander": {"santander.es", "santander.com"}, "caixabank": {"caixabank.es"}, "sabadell": {"bancsabadell.com", "sabadell.com"},
    "paypal": {"paypal.com"}, "amazon": {"amazon.es", "amazon.com"}, "apple": {"apple.com"},
    "microsoft": {"microsoft.com"}, "google": {"google.com", "google.es"}, "facebook": {"facebook.com"},
    "instagram": {"instagram.com"}, "booking": {"booking.com"}, "airbnb": {"airbnb.es", "airbnb.com"},
    "ticketmaster": {"ticketmaster.es"}, "bizum": {"bizum.es"}, "ing": {"ing.es"},
    "agenciatributaria": {"agenciatributaria.gob.es", "agenciatributaria.es"}, "dgt": {"dgt.es"},
    "netflix": {"netflix.com"}, "binance": {"binance.com"},
}
_SECOND_LEVEL = {"co.uk", "com.es", "gob.es", "org.es", "nom.es", "com.mx", "com.ar", "com.br"}
_HOMOGLYPH = str.maketrans({"0": "o", "1": "l", "3": "e", "5": "s", "4": "a", "7": "t", "$": "s"})


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def detect_url(url: str) -> tuple[list[Signal], str | None]:
    """Devuelve señales estructurales de la URL y el dominio registrable."""
    sigs: list[Signal] = []
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return sigs, None
    if not host:
        return sigs, None

    def add(code, ev, sev=0.9, cert=0.95):
        sigs.append(Signal(code=code, severity=sev, certainty=cert, verified=True, source="rule", evidence=ev))

    if parts.username or parts.password:
        add("URL_USERINFO_TRICK", f"El enlace contiene credenciales/usuario antes del dominio real ({host}).")
    try:
        ipaddress.ip_address(host)
        add("URL_RAW_IP", f"El enlace apunta directamente a la IP {host}.")
        return sigs, host
    except ValueError:
        pass
    if parts.scheme == "http":
        add("URL_NO_HTTPS", "El enlace usa http:// sin cifrado.", sev=0.7)
    reg = registrable_domain(host)
    if reg in SHORTENERS:
        add("URL_SHORTENER", f"{reg} es un acortador de enlaces.")
    tld = host.rsplit(".", 1)[-1]
    if tld in SUSPICIOUS_TLDS:
        add("URL_SUSPICIOUS_TLD", f"La extensión .{tld} se usa a menudo en campañas fraudulentas.", sev=0.7, cert=0.7)

    labels = host.split(".")
    sld = reg.split(".")[0]
    sld_norm = sld.translate(_HOMOGLYPH).replace("-", "")
    flagged = False
    for brand, official in BRANDS.items():
        if reg in official or flagged:
            continue
        tokens = {t.translate(_HOMOGLYPH) for lab in labels[:-1] for t in lab.split("-")}
        near = sld_norm != brand and len(brand) >= 5 and _lev(sld_norm, brand) <= 1
        contained = len(brand) >= 5 and brand in sld_norm and sld_norm != brand
        as_token = brand in tokens and reg not in official
        spoofed = "xn--" in host and brand in host.replace("xn--", "")
        if near or contained or as_token or spoofed:
            add("URL_LOOKALIKE_DOMAIN",
                f"El dominio {reg} recuerda a «{brand}» pero no es un dominio oficial de esa marca.")
            flagged = True
    if "xn--" in host and not flagged:
        add("URL_LOOKALIKE_DOMAIN", f"El dominio usa codificación internacional (punycode): {host}.", sev=0.6, cert=0.6)
    return sigs, reg


_AMOUNT = re.compile(r"(\d{1,3}(?:[.]\d{3})+|\d{1,7})(?:,(\d{1,2}))?\s?(?:€|eur\b|euros?)", re.I)


def extract_price(text: str) -> float | None:
    """Primer importe en euros escrito en el texto (heurístico); None si no hay."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + ("." + m.group(2) if m.group(2) else ""))

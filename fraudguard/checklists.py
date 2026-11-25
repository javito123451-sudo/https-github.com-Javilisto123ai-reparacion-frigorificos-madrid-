"""Guías de comprobación por categoría de producto (escáner presencial).

Son listas de QUÉ COMPROBAR y qué preguntar; no emiten veredicto de autenticidad. Contenido genérico y prudente:
la verificación definitiva siempre es documental o por un profesional autorizado / el fabricante.
"""
from __future__ import annotations

import re
import unicodedata

CATEGORIES: dict[str, dict] = {
    "reloj": {
        "label": "Reloj", "keywords": ["reloj", "rolex", "omega", "cartier", "breitling", "tag heuer", "patek", "audemars", "seiko", "casio g-shock"],
        "checks": [
            "Compara el modelo con las fotos oficiales de la web del fabricante: esfera, índices, agujas, corona y brazalete.",
            "Busca el número de serie y de referencia (según el modelo, en la caja, entre las asas o en el fondo) y comprueba que coincide con la factura o el certificado.",
            "Revisa la calidad del grabado y de las tipografías: deben ser nítidas y uniformes, sin bordes irregulares ni errores ortográficos.",
            "Valora peso, tacto y holgura del brazalete y de la corona; una diferencia clara con un original conocido es un indicio, no una prueba.",
            "Pide caja, documentación y factura de compra con datos del comprador original.",
        ],
        "questions": ["¿Dónde y cuándo lo compraste? ¿Tienes la factura?", "¿Puedo llevarlo a un relojero oficial o a una tasación antes de pagar?"],
        "professional": "La autenticidad de un reloj de lujo solo la certifica el fabricante, un servicio técnico oficial o un tasador/relojero acreditado.",
    },
    "bolso": {
        "label": "Bolso o complemento de marca", "keywords": ["bolso", "louis vuitton", "gucci", "chanel", "prada", "dior", "hermes", "cartera", "cinturon", "bandolera"],
        "checks": [
            "Compara con el producto oficial: forma, proporciones, posición y nitidez del logotipo y de los patrones.",
            "Examina costuras (regularidad, tensión, número de puntadas), herrajes (peso, grabados) y forro interior.",
            "Busca la etiqueta/código de fabricación y comprueba que es coherente con el modelo; no basta con que exista.",
            "Pide bolsa de tela, tarjeta, recibo y factura originales.",
            "Ten en cuenta que muchas falsificaciones copian bien lo visible: la compra segura es en tienda oficial o plataformas con autenticación.",
        ],
        "questions": ["¿Dónde lo compraste? ¿Tienes el recibo?", "¿Aceptas que lo autentique un profesional antes de comprarlo?"],
        "professional": "Para confirmar autenticidad usa el servicio de la marca o un servicio de autenticación profesional.",
    },
    "joya_oro": {
        "label": "Joya de oro o plata", "keywords": ["oro", "plata", "cadena", "anillo", "pulsera", "collar", "joya", "quilates", "kilates"],
        "checks": [
            "Busca el contraste/punzón (marca de ley, p. ej. 750 o 925) y de la casa fabricante en cierres y aros; su ausencia o un grabado tosco es un indicio.",
            "Las pruebas caseras (imán, color, peso a ojo) NO son concluyentes.",
            "Pide factura o certificado y comprueba el peso declarado con una balanza de precisión.",
            "Compra siempre con comprobante; compara con el precio del oro del día: un precio muy inferior a su valor de metal es una señal fuerte.",
        ],
        "questions": ["¿Tiene factura o certificado?", "¿Puedo pesarla y que la revise un joyero antes de pagar?"],
        "professional": "Un joyero o una casa de contraste puede analizar el metal (p. ej. con ensayo o fluorescencia de rayos X).",
    },
    "gemas": {
        "label": "Diamante o piedra preciosa", "keywords": ["diamante", "brillante", "esmeralda", "rubi", "zafiro", "gema", "piedra preciosa"],
        "checks": [
            "Pide certificado de un laboratorio gemológico reconocido y comprueba que el número coincide con la inscripción láser del canto (con lupa).",
            "Desconfía de piedras 'sueltas' sin certificado vendidas muy por debajo de su valor.",
            "Una foto no permite distinguir diamantes de imitaciones ni sintéticos: se necesita un gemólogo.",
        ],
        "questions": ["¿Qué laboratorio lo certificó y con qué número?", "¿Puedo llevarlo a un gemólogo independiente?"],
        "professional": "Solo un laboratorio o gemólogo acreditado puede identificar la piedra y su origen.",
    },
    "movil": {
        "label": "Teléfono móvil", "keywords": ["iphone", "samsung", "galaxy", "movil", "telefono", "pixel", "xiaomi", "huawei"],
        "checks": [
            "Marca *#06# y comprueba que el IMEI coincide con el de la caja y con el de Ajustes.",
            "Verifica que no está bloqueado por cuenta (bloqueo de activación / cuenta de Google) y que puedes cerrar la sesión del vendedor y restablecerlo delante de ti.",
            "Comprueba el estado de la batería, la pantalla, las cámaras y que reconoce una SIM.",
            "Desconfía de 'precintados' muy baratos y de cajas sin factura: pide comprobante de compra.",
            "Consulta si el IMEI figura como robado o bloqueado a través de los servicios del operador o de tu fabricante.",
        ],
        "questions": ["¿Puedo restablecerlo y activarlo yo aquí?", "¿Tienes factura y la caja con el mismo IMEI?"],
        "professional": "Ante dudas, compra en tiendas con garantía o con un reacondicionador reconocido.",
    },
    "electronica": {
        "label": "Consola, auriculares u otra electrónica", "keywords": ["consola", "playstation", "ps5", "xbox", "nintendo", "auriculares", "airpods", "macbook", "portatil", "tablet", "ipad", "smartwatch"],
        "checks": [
            "Comprueba número de serie en el aparato y en la caja y que sea coherente; pruébalo encendido y con todos los accesorios.",
            "Revisa embalaje, impresión de etiquetas y precintos: errores o calidad pobre son indicios.",
            "Para auriculares y accesorios, compara el emparejamiento y las funciones con las del producto original.",
            "Pide factura y garantía; desconfía si el vendedor no deja probarlo.",
        ],
        "questions": ["¿Puedo probarlo ahora mismo?", "¿Tienes factura y garantía?"],
        "professional": "Verifica el número de serie con el soporte del fabricante cuando ofrezca esa opción.",
    },
    "calzado_ropa": {
        "label": "Zapatillas o ropa de marca", "keywords": ["zapatillas", "nike", "adidas", "jordan", "ropa", "camiseta", "chaqueta", "sudadera"],
        "checks": [
            "Compara con fotos oficiales: logotipos, etiquetas interiores, costuras y materiales.",
            "Revisa la etiqueta con código de producto y busca ese código en la web oficial.",
            "Comprueba caja, papel de seda y etiquetas; las calidades de impresión irregulares son indicios.",
            "Compra con factura o a través de plataformas que autentican.",
        ],
        "questions": ["¿Tienes el ticket o la factura?", "¿Qué código de producto tiene la etiqueta interior?"],
        "professional": "Plataformas de reventa con autenticación o la propia marca pueden confirmarlo.",
    },
    "perfume": {
        "label": "Perfume o cosmética", "keywords": ["perfume", "colonia", "eau de", "fragancia", "cosmetica"],
        "checks": [
            "Comprueba el código de lote impreso en caja y frasco: deben coincidir.",
            "Revisa precinto, celofán, impresión del envase y nitidez de textos.",
            "Un precio muy inferior al de tiendas oficiales es la señal principal.",
        ],
        "questions": ["¿Se vende precintado y con ticket?", "¿De qué distribuidor procede?"],
        "professional": "Compra en perfumerías y tiendas oficiales.",
    },
    "gafas": {
        "label": "Gafas", "keywords": ["gafas", "ray-ban", "rayban", "oakley", "gafas de sol"],
        "checks": [
            "Compara logotipos, grabados interiores de la varilla y bisagras con las del modelo oficial.",
            "Revisa estuche, paño y etiquetas.",
            "La protección UV no se puede comprobar a simple vista.",
        ],
        "questions": ["¿Tienes factura o estuche original?"],
        "professional": "Una óptica oficial puede revisar si es original.",
    },
}

GENERIC = {
    "label": "Producto",
    "checks": ["Pide factura y comprobante de compra y comprueba que los datos coinciden con el producto.",
               "Compara con fotos oficiales del fabricante.", "No pagues hasta poder comprobarlo con calma."],
    "questions": ["¿Puedo comprobarlo con un profesional antes de pagar?"],
    "professional": "Ante dudas, solo un profesional autorizado o el fabricante puede certificar autenticidad.",
}

UNIVERSAL_TIPS = [
    "No pagues en efectivo bajo presión. Un vendedor honesto te deja comprobarlo con calma.",
    "Si el precio es mucho menor que el de tienda, pregúntate por qué: es la señal más habitual.",
    "Una foto o este análisis NO certifican autenticidad; solo señalan indicios.",
]


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(c))


def detect_category(explicit: str | None, *texts: str | None) -> str | None:
    if explicit in CATEGORIES:
        return explicit
    hay = _fold(" ".join(t for t in texts if t))
    best, hits = None, 0
    for key, c in CATEGORIES.items():
        n = sum(1 for k in c["keywords"] if re.search(rf"\b{re.escape(_fold(k))}", hay))
        if n > hits:
            best, hits = key, n
    return best


def checklist_for(category: str | None) -> dict:
    c = CATEGORIES.get(category or "", GENERIC)
    return {"category": category or "generic", "label": c["label"], "checks": c["checks"], "questions": c["questions"],
            "professional": c["professional"], "tips": UNIVERSAL_TIPS}

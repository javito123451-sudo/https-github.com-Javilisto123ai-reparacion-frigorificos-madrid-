"""Catálogo CERRADO de señales. Ni el LLM ni las reglas pueden emitir códigos fuera de él.

Garantía de equidad: ninguna señal se refiere a rasgos personales del vendedor
(aspecto, origen, nacionalidad...). Hay un test que lo vigila.
Los pesos son PROVISIONALES: deben calibrarse con datos reales (ver eval/).
"""
from __future__ import annotations

from dataclasses import dataclass

RULESET_VERSION = "2026.11-a"


@dataclass(frozen=True)
class SignalDef:
    code: str
    category: str
    weight: float
    title: str
    advice: str
    definition: str  # para el prompt del LLM


def _s(code, category, weight, title, advice, definition):
    return code, SignalDef(code, category, weight, title, advice, definition)


CATALOG: dict[str, SignalDef] = dict([
    _s("ADVANCE_PAYMENT_REQUESTED", "pago", 0.60, "Piden un pago por adelantado (señal/reserva)",
       "No pagues por adelantado a desconocidos. Paga solo al recibir y comprobar, o con el pago protegido de la plataforma.",
       "Se exige dinero antes de poder ver o recibir el producto/servicio (señal, reserva, adelanto)."),
    _s("PAYMENT_UNTRACEABLE", "pago", 0.55, "Método de pago difícil de rastrear o revertir",
       "Evita tarjetas regalo, criptomonedas, Western Union o similares: si es un fraude, no se recupera.",
       "Se pide pagar con gift cards, criptomonedas, Western Union/MoneyGram, Paysafecard u otro medio irreversible."),
    _s("OFF_PLATFORM_PAYMENT", "pago", 0.55, "Piden pagar fuera de la plataforma o con un enlace externo",
       "Paga únicamente dentro de la plataforma oficial. Un enlace de pago enviado por el vendedor es una táctica de estafa habitual.",
       "Se propone pagar fuera de la plataforma de compraventa o mediante un enlace/pasarela ajena."),
    _s("FAKE_PAYMENT_LINK", "suplantación", 0.70, "Enlace de 'cobro' o 'seguro de envío' que imita a una plataforma o transportista",
       "No abras enlaces para 'cobrar' una venta. Los cobros legítimos no requieren que introduzcas datos de tu tarjeta.",
       "Se envía un enlace supuestamente de la plataforma/transportista para cobrar, confirmar o pagar un seguro de envío."),
    _s("OFF_PLATFORM_CONTACT", "contacto", 0.25, "Intentan sacar la conversación a WhatsApp/Telegram",
       "Mantén la conversación dentro de la plataforma: así queda constancia y te protege.",
       "Se insiste en continuar la conversación por WhatsApp, Telegram u otro canal externo."),
    _s("URGENCY_PRESSURE", "presión", 0.30, "Presión para decidir o pagar con prisa",
       "Una prisa extrema es una táctica de manipulación. Tómate el tiempo que necesites para comprobar.",
       "Se presiona con plazos, 'última oportunidad' o con que hay otros interesados para que se decida sin pensar."),
    _s("EMOTIONAL_PRESSURE_STORY", "presión", 0.20, "Historia emocional para presionar",
       "Una historia triste no es una prueba. Decide solo con hechos comprobables.",
       "Se usa una historia personal (necesidad de dinero, enfermedad, deuda) para justificar el precio o la prisa."),
    _s("SENSITIVE_DATA_REQUESTED", "datos", 0.75, "Piden datos sensibles (códigos, claves, DNI, tarjeta)",
       "No compartas códigos SMS, claves, CVV ni fotos de tu DNI o tarjeta. Ninguna compraventa legítima los necesita.",
       "Se pide el código de verificación SMS, contraseña, PIN, CVV, número de tarjeta/cuenta o documentos de identidad."),
    _s("IMPERSONATION_AUTHORITY", "suplantación", 0.55, "Se hacen pasar por un banco, organismo o empresa",
       "Contacta con la entidad por sus canales oficiales (no por el enlace o teléfono del mensaje). INCIBE: 017.",
       "El mensaje dice proceder de un banco, Hacienda, policía, Correos, etc., alertando de un problema o reembolso."),
    _s("IMPERSONATION_RELATIVE", "suplantación", 0.60, "Alguien dice ser un familiar con 'nuevo número' y pide dinero",
       "Llama al familiar a su número de siempre antes de enviar dinero. Es una estafa muy extendida por WhatsApp.",
       "Un mensaje dice ser un familiar (hijo/a, madre, padre...) con un número nuevo o sin móvil y pide dinero con urgencia."),
    _s("GUARANTEED_RETURNS", "inversión", 0.70, "Promesa de rentabilidad garantizada o sin riesgo",
       "Ninguna inversión legítima garantiza beneficios. Comprueba la entidad en los registros de la CNMV.",
       "Se prometen beneficios garantizados, muy altos o 'sin riesgo'."),
    _s("UNREALISTIC_PROMISES", "señuelo", 0.35, "Premios o regalos inesperados",
       "Nadie regala dinero ni premios sin que hayas participado. No pagues 'tasas' para recibirlos.",
       "Se anuncia un premio, sorteo o regalo inesperado."),
    _s("PRICE_FAR_BELOW_REFERENCE", "precio", 0.50, "Precio muy por debajo del valor de referencia",
       "Un precio irreal es la señal más habitual de producto falso o inexistente. Verifica el valor real antes de pagar.",
       "El precio es muy inferior al de referencia aportado por el usuario. NO lo emitas tú salvo que el texto declare explícitamente el valor real."),
    _s("SELLER_BLOCKS_INSPECTION", "verificación", 0.35, "Impiden o dificultan comprobar el producto",
       "No compres sin poder revisar el artículo. Un vendedor honesto permite comprobarlo.",
       "Se impide probar, revisar o verificar el producto o la identidad antes de pagar."),
    _s("CASH_IMMEDIATE_DEMAND", "pago", 0.30, "Exigen efectivo inmediato",
       "No entregues dinero en efectivo bajo presión. Si dudas, no compres.",
       "Se exige efectivo ahora mismo o solo efectivo, sin margen para comprobar."),
    _s("UNSOLICITED_OFFER", "situación", 0.30, "Oferta no solicitada de un producto de valor",
       "Las ofertas espontáneas de relojes, joyas o móviles 'de lujo' suelen ser engaños. Desconfía.",
       "Alguien ofrece espontáneamente (p. ej. en la calle) un producto de valor muy por debajo de su precio."),
    _s("NO_VERIFIABLE_DOCUMENTATION", "verificación", 0.15, "Sin factura, caja ni documentación verificable",
       "Pide factura, número de serie y comprobante de compra; verifica el número de serie con el fabricante.",
       "No hay factura, caja, certificado, número de serie u otra documentación verificable."),
    _s("AUTHENTICITY_CLAIM_UNVERIFIED", "verificación", 0.15, "Afirman autenticidad sin pruebas",
       "Una frase como '100% original' no prueba nada. Solo un profesional autorizado certifica la autenticidad.",
       "Se asegura que el producto es 'original/auténtico' sin aportar prueba."),
    _s("VISUAL_INCONSISTENCY", "imagen", 0.35, "Detalles visuales inconsistentes con el producto anunciado",
       "Compáralo con fotos oficiales y consulta a un profesional autorizado antes de pagar.",
       "En la imagen se ve un detalle CONCRETO y visible (logotipo, tipografía, grabado, costura, etiqueta) incoherente con la marca/modelo. Nunca por impresión general."),
    _s("CONTACT_INCONSISTENT", "contacto", 0.25, "Datos contradictorios",
       "Pide aclaraciones y no avances si las respuestas no cuadran.",
       "Hay contradicciones entre nombre, ubicación, producto, precio o historia."),
    _s("URL_USERINFO_TRICK", "url", 0.55, "Enlace con truco de usuario@dominio",
       "El dominio real es el que aparece tras la arroba. No abras este enlace.", "(solo reglas)"),
    _s("URL_RAW_IP", "url", 0.45, "El enlace usa una dirección IP en lugar de un dominio",
       "Los servicios legítimos no suelen usar IPs en sus enlaces.", "(solo reglas)"),
    _s("URL_LOOKALIKE_DOMAIN", "url", 0.55, "Dominio que imita a una marca conocida",
       "Escribe tú mismo la dirección oficial en el navegador; no uses este enlace.", "(solo reglas)"),
    _s("URL_SHORTENER", "url", 0.25, "Enlace acortado que oculta el destino",
       "No puedes saber a dónde lleva realmente. Pide el enlace completo.", "(solo reglas)"),
    _s("URL_SUSPICIOUS_TLD", "url", 0.15, "Extensión de dominio muy usada en campañas fraudulentas",
       "No es concluyente por sí sola; combínala con el resto de comprobaciones.", "(solo reglas)"),
    _s("URL_NO_HTTPS", "url", 0.15, "El sitio no usa conexión cifrada (HTTP)",
       "No introduzcas datos personales ni de pago en sitios sin HTTPS.", "(solo reglas)"),
    _s("DOMAIN_RECENTLY_REGISTERED", "url", 0.45, "Dominio registrado hace muy poco (verificado por RDAP)",
       "Las tiendas fraudulentas suelen usar dominios de semanas de vida. Busca opiniones independientes.", "(solo verificación)"),
])

MITIGATORS: dict[str, tuple[str, float, str]] = {
    # code: (título, reducción máxima del riesgo, definición para el LLM)
    "PROTECTED_PAYMENT_USED": ("Se usa el pago protegido de la plataforma", 0.30,
                               "La operación se hace íntegramente con pago/envío protegido de una plataforma conocida."),
    "IN_PERSON_CHECK_ALLOWED": ("Permiten ver y probar el producto en persona", 0.15,
                                "El vendedor ofrece explícitamente que se vea/pruebe el producto en un lugar público antes de pagar."),
    "DOCUMENTATION_PROVIDED": ("Se ofrece factura, garantía o documentación", 0.12,
                               "Se menciona factura, garantía, certificado o caja con papeles."),
    "DOMAIN_ESTABLISHED": ("Dominio con varios años de antigüedad (verificado por RDAP)", 0.15, "(solo verificación)"),
}

BANDS = [(20, "bajo", "Riesgo bajo"), (40, "moderado", "Riesgo moderado"),
         (60, "elevado", "Riesgo elevado"), (80, "alto", "Riesgo alto"), (100, "critico", "Riesgo crítico")]


def band_for(score: int) -> tuple[str, str]:
    for top, key, label in BANDS:
        if score <= top:
            return key, label
    return "critico", "Riesgo crítico"

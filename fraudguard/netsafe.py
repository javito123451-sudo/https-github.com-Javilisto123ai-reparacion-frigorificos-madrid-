"""Acceso saliente seguro: protección SSRF, tamaño y redirecciones acotadas. Solo lectura pasiva (sin JS).

Cada salto de redirección se vuelve a validar. La petición se fija a la IP ya validada
(con SNI/Host originales) para evitar DNS rebinding entre la validación y la conexión.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx2 as httpx

MAX_URL_LEN = 2048
ALLOWED_PORTS = {None, 80, 443}
USER_AGENT = "FraudGuard-Analyzer/0.1 (+passive; no-js)"


class UnsafeURL(ValueError):
    """La URL no se puede analizar de forma segura."""


class UnresolvableURL(UnsafeURL):
    """El dominio no resuelve (puede estar caído): se puede analizar la URL, pero no descargarla."""


@dataclass
class Target:
    url: str
    scheme: str
    host: str
    ip: str
    path_qs: str


def _resolve_default(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list({i[4][0] for i in infos})


def validate_public_url(url: str, *, resolver=_resolve_default, allow_private: bool = False) -> Target:
    if not url or len(url) > MAX_URL_LEN:
        raise UnsafeURL("URL vacía o demasiado larga.")
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError:
        raise UnsafeURL("URL mal formada.")
    if p.scheme not in ("http", "https"):
        raise UnsafeURL("Solo se admiten enlaces http:// o https://.")
    if p.username or p.password:
        raise UnsafeURL("No se admiten enlaces con usuario/contraseña.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Puerto no permitido.")
    host = (p.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
        raise UnsafeURL("Destino no permitido.")
    try:
        host_idna = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise UnsafeURL("Nombre de dominio inválido.")
    try:
        ips = [host_idna] if _is_ip(host_idna) else resolver(host_idna)
    except OSError:
        raise UnresolvableURL("No se pudo resolver el dominio.")
    if not ips:
        raise UnresolvableURL("No se pudo resolver el dominio.")
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if not addr.is_global and not allow_private:
            raise UnsafeURL("El destino no es una dirección pública de Internet.")
        if getattr(addr, "ipv4_mapped", None) and not addr.ipv4_mapped.is_global and not allow_private:
            raise UnsafeURL("El destino no es una dirección pública de Internet.")
    path_qs = (p.path or "/") + (f"?{p.query}" if p.query else "")
    return Target(url=url.strip(), scheme=p.scheme, host=host_idna, ip=ips[0], path_qs=path_qs)


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


@dataclass
class FetchResult:
    final_url: str
    status: int
    content_type: str
    text: str
    redirects: list[str] = field(default_factory=list)
    truncated: bool = False


def safe_fetch(url: str, *, max_bytes: int = 1_000_000, max_redirects: int = 3, timeout: float = 8.0,
               accept_types: tuple[str, ...] = ("text/html", "text/plain", "application/xhtml"),
               resolver=_resolve_default, allow_private: bool = False, trust_env: bool = False,
               client: httpx.Client | None = None) -> FetchResult:
    own = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=False, trust_env=trust_env)
    redirects: list[str] = []
    current = url
    try:
        for _ in range(max_redirects + 1):
            t = validate_public_url(current, resolver=resolver, allow_private=allow_private)
            ip_host = f"[{t.ip}]" if ":" in t.ip else t.ip
            pinned = f"{t.scheme}://{ip_host}{t.path_qs}"
            headers = {"Host": t.host, "User-Agent": USER_AGENT, "Accept": ",".join(accept_types) + ";q=0.9,*/*;q=0.1"}
            with client.stream("GET", pinned, headers=headers, extensions={"sni_hostname": t.host}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                    nxt = urljoin(current, r.headers["location"])
                    redirects.append(nxt)
                    current = nxt
                    continue
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not any(ctype.startswith(a) or ctype.endswith("json") and any(x.endswith("json") for x in accept_types)
                           for a in accept_types) and ctype:
                    raise UnsafeURL(f"Tipo de contenido no admitido ({ctype}).")
                buf, truncated = bytearray(), False
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        truncated = True
                        del buf[max_bytes:]
                        break
                enc = r.encoding or "utf-8"
                return FetchResult(final_url=current, status=r.status_code, content_type=ctype,
                                   text=bytes(buf).decode(enc, errors="replace"), redirects=redirects, truncated=truncated)
        raise UnsafeURL("Demasiadas redirecciones.")
    finally:
        if own:
            client.close()


# ------------------------------------------------------------------ HTML → texto
class _Extractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self.has_password = False
        self.has_card = False
        self.hosts: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "input":
            if (a.get("type") or "").lower() == "password":
                self.has_password = True
            n = f"{a.get('name','')} {a.get('autocomplete','')} {a.get('id','')}".lower()
            if any(k in n for k in ("cc-number", "cardnumber", "card-number", "cvv", "cvc")):
                self.has_card = True
        if tag == "a" and a.get("href", "").startswith("http"):
            h = urlsplit(a["href"]).hostname
            if h:
                self.hosts.add(h.lower())

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data.strip())


@dataclass
class PageInfo:
    title: str
    text: str
    has_password_input: bool
    has_card_input: bool
    external_hosts: list[str]


def extract_page(html: str, max_chars: int = 6000) -> PageInfo:
    p = _Extractor()
    try:
        p.feed(html)
    except Exception:  # HTML roto: usar lo acumulado
        pass
    text = " ".join(p.parts)
    return PageInfo(title=p.title.strip()[:200], text=text[:max_chars], has_password_input=p.has_password,
                    has_card_input=p.has_card, external_hosts=sorted(p.hosts)[:30])

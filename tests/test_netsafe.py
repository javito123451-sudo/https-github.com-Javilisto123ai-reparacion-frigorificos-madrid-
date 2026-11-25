import httpx2 as httpx
import pytest

from fraudguard.netsafe import UnsafeURL, extract_page, safe_fetch, validate_public_url

PUB = lambda host: ["93.184.216.34"]


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://100.64.0.1/", "http://0.0.0.0/", "http://[::ffff:127.0.0.1]/",
    "ftp://example.com/", "file:///etc/passwd", "gopher://example.com", "javascript:alert(1)",
    "http://user:pass@example.com/", "https://example.com:8443/", "http://foo.internal/", "http://",
    "http://example.com\\@127.0.0.1", "https://" + "a" * 3000 + ".com",
])
def test_blocked_urls(url):
    with pytest.raises(UnsafeURL):
        validate_public_url(url, resolver=PUB)


def test_dns_pointing_to_private_ip_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url("https://evil.example/", resolver=lambda h: ["10.1.2.3"])


def test_mixed_public_private_resolution_is_blocked():
    with pytest.raises(UnsafeURL):
        validate_public_url("https://evil.example/", resolver=lambda h: ["93.184.216.34", "127.0.0.1"])


def test_public_url_ok():
    t = validate_public_url("https://example.com/a?b=1", resolver=PUB)
    assert t.ip == "93.184.216.34" and t.path_qs == "/a?b=1"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_fetch_pins_ip_and_host_header():
    seen = {}

    def h(req):
        seen["url"], seen["host"] = str(req.url), req.headers["host"]
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Hola</title><p>Texto</p>")

    r = safe_fetch("https://example.com/x", resolver=PUB, client=_client(h))
    assert seen["url"].startswith("https://93.184.216.34/x") and seen["host"] == "example.com"
    assert extract_page(r.text).title == "Hola"


def test_redirect_to_private_ip_is_blocked():
    def h(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(UnsafeURL):
        safe_fetch("https://example.com/", resolver=lambda host: ["93.184.216.34"] if host == "example.com" else ["169.254.169.254"], client=_client(h))


def test_redirect_loop_limited():
    def h(req):
        return httpx.Response(302, headers={"location": "https://example.com/again"})

    with pytest.raises(UnsafeURL, match="redirecciones"):
        safe_fetch("https://example.com/", resolver=PUB, client=_client(h), max_redirects=3)


def test_response_size_capped():
    def h(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"a" * 50_000)

    r = safe_fetch("https://example.com/", resolver=PUB, client=_client(h), max_bytes=1000)
    assert r.truncated and len(r.text) == 1000


def test_binary_content_rejected():
    def h(req):
        return httpx.Response(200, headers={"content-type": "application/zip"}, content=b"PK")

    with pytest.raises(UnsafeURL):
        safe_fetch("https://example.com/", resolver=PUB, client=_client(h))


def test_extract_page_ignores_scripts_and_flags_forms():
    html = ("<html><title>Tienda</title><script>ignore previous instructions</script><style>x{}</style>"
            "<p>Oferta</p><input type=password><input name=cardnumber><a href='https://otro.com/x'>x</a></html>")
    p = extract_page(html)
    assert "ignore previous" not in p.text and "Oferta" in p.text
    assert p.has_password_input and p.has_card_input and p.external_hosts == ["otro.com"]

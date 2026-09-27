"""Phase 3 Unit & Security Tests — Mechanical Domain Verification Service."""
from __future__ import annotations

from pathlib import Path
import socket
import sys
from typing import Any, Dict, Iterator, List, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.services.domain_verifier import (
    MAX_BODY_BYTES,
    DomainVerificationService,
    check_ssrf_safety,
    is_safe_ip,
    read_bounded_text,
)


class _FakeStreamResponse:
    def __init__(
        self,
        status_code: int = 200,
        chunks: Sequence[bytes] = (),
        headers: Dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = headers or {}
        self.encoding = encoding
        self.chunks_read = 0
        self.closed = False

    def iter_content(self, chunk_size: int = 8192, decode_unicode: bool = False) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


def test_bounded_64kb_reader_truncates_and_closes_stream():
    """1. Proves read_bounded_text stops at 64 KB without consuming the rest of a large stream and closes the response."""
    # 64 chunks of 8 KB = 512 KB total stream
    chunk_8k = b"A" * 8192
    resp = _FakeStreamResponse(status_code=200, chunks=[chunk_8k for _ in range(64)])

    text, total_bytes = read_bounded_text(resp)
    assert total_bytes == MAX_BODY_BYTES == 65536
    assert len(text) == 65536
    # Only 8 chunks (8 * 8192 = 65536) should have been consumed from the iterator
    assert resp.chunks_read == 8
    assert resp.closed is True


def test_ipv4_mapped_ipv6_and_cloud_metadata_ssrf_blocks():
    """2. Proves IPv4-mapped IPv6, loopback, private, link-local, metadata IPs, and non-web ports are blocked."""
    unsafe_ips = [
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "169.254.169.254",
        "::ffff:169.254.169.254",
        "10.0.0.1",
        "::ffff:10.0.0.1",
        "192.168.1.10",
        "::ffff:192.168.1.10",
        "172.16.5.4",
        "::ffff:172.16.5.4",
        "100.100.100.200",
        "fd00:ec2::254",
        "0.0.0.0",
        "::",
    ]
    for ip_str in unsafe_ips:
        safe, reason = is_safe_ip(ip_str)
        assert safe is False, f"Expected IP {ip_str} to be blocked, but got safe=True"
        assert "blocked" in reason.lower()

    safe_pub, _ = is_safe_ip("93.184.216.34")
    assert safe_pub is True

    # Disallowed scheme & port checks
    safe_ftp, reason_ftp, _, _ = check_ssrf_safety("ftp://example.com/file")
    assert safe_ftp is False and "scheme" in reason_ftp.lower()

    safe_port, reason_port, _, _ = check_ssrf_safety("https://example.com:6379/redis")
    assert safe_port is False and "port" in reason_port.lower()

    # DNS resolving to IPv4-mapped IPv6 metadata address must be blocked
    safe_mapped, reason_mapped, _, _ = check_ssrf_safety(
        "https://evil-rebind.example.com",
        dns_resolver=lambda host, port: ["::ffff:169.254.169.254"],
    )
    assert safe_mapped is False
    assert "169.254.169.254" in reason_mapped


def test_pinned_dns_resolution_prevents_dns_rebinding():
    """3. Proves that during outbound HTTP fetch, socket.getaddrinfo is pinned to the validated public IP."""
    observed_resolved_ips_inside_get: List[str] = []

    def fake_dns_resolver(host: str, port: int) -> Sequence[str]:
        # Initial check returns safe public IP
        return ["93.184.216.34"]

    def fake_http_get(url: str, **kwargs: Any) -> _FakeStreamResponse:
        # Inside the HTTP client, if urllib3 calls socket.getaddrinfo("rebind.example.com", 443),
        # pinned_dns_resolution must return the pinned public IP (93.184.216.34), never an unvalidated lookup.
        info = socket.getaddrinfo("rebind.example.com", 443, type=socket.SOCK_STREAM)
        observed_resolved_ips_inside_get.append(str(info[0][4][0]))
        return _FakeStreamResponse(status_code=200, chunks=[b"<html><body>Active Shop</body></html>"])

    service = DomainVerificationService(dns_resolver=fake_dns_resolver, http_get=fake_http_get)
    res = service.verify("https://rebind.example.com")

    assert res.reachable is True
    assert res.pinned_ip == "93.184.216.34"
    assert observed_resolved_ips_inside_get == ["93.184.216.34"]


def test_redirect_chain_blocks_ssrf_on_subsequent_hop():
    """4. Proves that a redirect from a public domain to an internal/metadata IP is blocked before connecting."""
    def fake_dns(host: str, port: int) -> Sequence[str]:
        if host == "publicbrand.in":
            return ["93.184.216.34"]
        return ["127.0.0.1"]

    def fake_get(url: str, **kwargs: Any) -> _FakeStreamResponse:
        if "publicbrand.in" in url:
            return _FakeStreamResponse(
                status_code=302,
                headers={"Location": "http://169.254.169.254/latest/meta-data"},
            )
        raise AssertionError("Verifier must never issue HTTP request to metadata redirect target")

    service = DomainVerificationService(dns_resolver=fake_dns, http_get=fake_get)
    res = service.verify("https://publicbrand.in")

    assert res.reachable is False
    assert res.error_code == "SSRF_BLOCKED"
    assert res.storefront_state == "dead"
    assert res.redirect_chain == ["https://publicbrand.in", "http://169.254.169.254/latest/meta-data"]


def test_expressive_http_and_storefront_states():
    """5. Proves 404 -> page_available=False/dead, 403 -> page_available=None/unknown, and /password -> password_locked."""
    pub_dns = lambda host, port: ["93.184.216.34"]

    # Case A: 404 Not Found -> reachable=True, page_available=False, storefront_state="dead"
    srv_404 = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=404, chunks=[b"Not Found"]),
    )
    res_404 = srv_404.verify("https://missing-page.in")
    assert res_404.reachable is True
    assert res_404.http_status == 404
    assert res_404.page_available is False
    assert res_404.storefront_state == "dead"

    # Case B: 403 Forbidden (bot wall) -> reachable=True, page_available=None (UNKNOWN), storefront_state="unknown"
    srv_403 = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=403, chunks=[b"Cloudflare challenge"]),
    )
    res_403 = srv_403.verify("https://protected-brand.in")
    assert res_403.reachable is True
    assert res_403.http_status == 403
    assert res_403.page_available is None
    assert res_403.storefront_state == "unknown"

    # Case C: Shopify store redirecting to /password -> platform="Shopify", storefront_state="password_locked"
    def password_redirect_get(url: str, **kw: Any) -> _FakeStreamResponse:
        if url.endswith("/password"):
            html = (
                b'<html><head><script src="https://cdn.shopify.com/s/files/1/shop.js"></script></head>'
                b'<body><form action="/password" id="password-login">Opening Soon</form></body></html>'
            )
            return _FakeStreamResponse(status_code=200, chunks=[html], headers={"x-shopid": "998877"})
        return _FakeStreamResponse(status_code=302, headers={"Location": "https://unreleased.in/password"})

    srv_pw = DomainVerificationService(dns_resolver=pub_dns, http_get=password_redirect_get)
    res_pw = srv_pw.verify("https://unreleased.in")
    assert res_pw.reachable is True
    assert res_pw.page_available is True
    assert res_pw.platform == "Shopify"
    assert res_pw.platform_confidence == "HIGH"
    assert res_pw.storefront_state == "password_locked"


def test_wordpress_blog_mentioning_woocommerce_is_not_classified_as_woocommerce():
    """6. Proves a WordPress blog mentioning 'WooCommerce' in article text is not misclassified as a WooCommerce store."""
    pub_dns = lambda host, port: ["93.184.216.34"]
    wp_blog_html = (
        b'<html><head><link rel="stylesheet" href="/wp-content/themes/twenty/style.css"></head>'
        b"<body><article>Why many brands compare WooCommerce and custom headless setups.</article></body></html>"
    )
    srv_blog = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=200, chunks=[wp_blog_html]),
    )
    res_blog = srv_blog.verify("https://techblog.example.com")
    assert res_blog.platform == "UNKNOWN"
    assert res_blog.platform_confidence == "NONE"

    # Real WooCommerce store with plugin asset + woocommerce_params JS variable
    wc_store_html = (
        b'<html><head><script src="/wp-content/plugins/woocommerce/assets/js/frontend/woocommerce.min.js"></script></head>'
        b'<body class="woocommerce woocommerce-page"><script>var woocommerce_params = {"ajax_url":"/?wc-ajax=%%endpoint%%"};</script></body></html>'
    )
    srv_wc = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=200, chunks=[wc_store_html]),
    )
    res_wc = srv_wc.verify("https://realwoostore.in")
    assert res_wc.platform == "WooCommerce"
    assert res_wc.platform_confidence == "HIGH"
    plat_ev = [e for e in res_wc.evidence if e.supports_field == "platform"]
    assert len(plat_ev) >= 2
    assert all(e.extracted_value == "WooCommerce" for e in plat_ev)


def test_structural_app_evidence_vs_plain_text_mentions():
    """7. Proves plain-text app mentions are ignored while script/widget footprints produce HIGH-confidence VerificationEvidence."""
    pub_dns = lambda host, port: ["93.184.216.34"]
    plain_text_html = (
        b"<html><body><p>We wrote a blog post reviewing Judge.me, Wati, and Klaviyo.</p></body></html>"
    )
    srv_plain = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=200, chunks=[plain_text_html]),
    )
    res_plain = srv_plain.verify("https://agencyblog.in")
    assert res_plain.detected_apps == []

    active_app_html = (
        b'<html><head>'
        b'<script src="https://cdn.shopify.com/s/files/1/store.js"></script>'
        b'<script src="https://cdn.judge.me/widget_preloader.js"></script>'
        b'<script src="https://wati-integration-prod-service.clare.ai/wati.io/wati.js"></script>'
        b'</head><body><div class="jdgm-widget jdgm-review-widget"></div></body></html>'
    )
    srv_active = DomainVerificationService(
        dns_resolver=pub_dns,
        http_get=lambda url, **kw: _FakeStreamResponse(status_code=200, chunks=[active_app_html]),
    )
    res_active = srv_active.verify("https://d2cbrand.in")
    assert res_active.platform == "Shopify"
    assert set(res_active.detected_apps) == {"Judge.me", "Wati"}
    app_ev = [e for e in res_active.evidence if e.supports_field == "installed_apps"]
    assert {e.extracted_value for e in app_ev} == {"Judge.me", "Wati"}
    assert all(len(e.content_hash) == 64 for e in app_ev)


def test_targeted_subpath_verification_aggregates_product_page_apps():
    """8. Proves verify(url, paths=['/', '/products/sample']) aggregates product-page app footprints."""
    pub_dns = lambda host, port: ["93.184.216.34"]

    def multi_path_get(url: str, **kw: Any) -> _FakeStreamResponse:
        if url.endswith("/products/sample"):
            return _FakeStreamResponse(
                status_code=200,
                chunks=[b'<html><head><script src="https://cdn.fera.ai/js/fera.js"></script></head></html>'],
            )
        return _FakeStreamResponse(
            status_code=200,
            chunks=[b'<html><head><script src="https://cdn.shopify.com/s/files/1/main.js"></script></head></html>'],
        )

    srv = DomainVerificationService(dns_resolver=pub_dns, http_get=multi_path_get)
    res = srv.verify("https://skincarebrand.in", paths=["/", "/products/sample"])
    assert res.platform == "Shopify"
    assert "Fera" in res.detected_apps
    assert any(e.supports_field == "installed_apps" and e.extracted_value == "Fera" for e in res.evidence)


if __name__ == "__main__":
    test_bounded_64kb_reader_truncates_and_closes_stream()
    test_ipv4_mapped_ipv6_and_cloud_metadata_ssrf_blocks()
    test_pinned_dns_resolution_prevents_dns_rebinding()
    test_redirect_chain_blocks_ssrf_on_subsequent_hop()
    test_expressive_http_and_storefront_states()
    test_wordpress_blog_mentioning_woocommerce_is_not_classified_as_woocommerce()
    test_structural_app_evidence_vs_plain_text_mentions()
    test_targeted_subpath_verification_aggregates_product_page_apps()
    print("8 passed")

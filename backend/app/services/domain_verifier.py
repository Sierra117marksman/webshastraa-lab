"""Mechanical SSRF-Safe Domain Verification Service for Maya v2 (Phase 3).

Responsibilities:
1. Bounded 64 KB response body reading (`read_bounded_text`) that stops streaming
   at `MAX_BODY_BYTES` and closes the socket immediately.
2. IPv4-mapped IPv6 (`::ffff:127.0.0.1`, `::ffff:169.254.169.254`), 6to4, and Teredo
   normalization before SSRF IP classification.
3. Anti-DNS-rebinding pinned-IP connection context so the socket connects strictly
   to the validated public IP while preserving `Host` header and TLS SNI.
4. Manual redirect-hop validation with SSRF re-verification on every hop.
5. Expressive HTTP reachability (`reachable`, `http_status`, `page_available`) and
   `storefront_state` (`active`, `password_locked`, `maintenance`, `dead`, `unknown`).
6. Signal-typed `VerificationEvidence` generation separating structural HTML/header
   footprints from plain-text mentions (e.g. WordPress blog vs WooCommerce store).
"""
from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import re
import socket
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Sequence, Tuple
import urllib.parse
from pydantic import BaseModel, Field, model_validator
import requests

from app.agents.schemas.candidate import StorefrontState
from app.agents.schemas.evidence import ConfidenceLevel, VerificationEvidence

VERIFIER_VERSION = "v2.0"
MAX_BODY_BYTES = 64 * 1024  # 65,536 bytes hard cap
CHUNK_READ_BYTES = 8192

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
    "metadata.internal",
}

CLOUD_METADATA_IPS = {
    "169.254.169.254",  # AWS, GCP, Azure, DigitalOcean
    "100.100.100.200",  # Alibaba Cloud
    "fd00:ec2::254",    # AWS IPv6 metadata
}

ALLOWED_PORTS = {80, 443, 8080, 8443}


class DomainVerificationResult(BaseModel):
    """Mechanical verification output for a candidate URL."""
    verifier_version: str = VERIFIER_VERSION
    initial_url: str
    final_url: str
    reachable: bool = False
    http_status: Optional[int] = None
    page_available: Optional[bool] = None
    storefront_state: StorefrontState = "unknown"
    redirect_chain: List[str] = Field(default_factory=list)
    platform: str = "UNKNOWN"
    platform_confidence: Literal["HIGH", "MEDIUM", "LOW", "NONE"] = "NONE"
    detected_apps: List[str] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    evidence: List[VerificationEvidence] = Field(default_factory=list)
    pinned_ip: Optional[str] = None
    bytes_read: int = 0
    error_code: Optional[str] = None
    error_detail: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _sync_legacy_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if "status_code" in data and "http_status" not in data:
            data["http_status"] = data.pop("status_code")
        if "error" in data and "error_detail" not in data:
            data["error_detail"] = data.pop("error")
        return data

    @property
    def status_code(self) -> Optional[int]:
        """Backward-compatible alias for `http_status`."""
        return self.http_status

    @status_code.setter
    def status_code(self, val: Optional[int]) -> None:
        self.http_status = val

    @property
    def error(self) -> Optional[str]:
        """Backward-compatible alias for `error_detail`."""
        return self.error_detail

    @error.setter
    def error(self, val: Optional[str]) -> None:
        self.error_detail = val


def normalize_ip_address(
    ip_str: str,
) -> UnionIPAddress:
    """Parse an IP literal and unwrap IPv4-mapped IPv6, 6to4, or Teredo addresses."""
    raw = (ip_str or "").strip()
    if "%" in raw:
        raw = raw.split("%", 1)[0]
    ip = ipaddress.ip_address(raw)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        if ip.teredo is not None:
            # Check server & client IP in Teredo tuple; unwrap client IP
            return ip.teredo[1]
    return ip


UnionIPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def is_safe_ip(ip_str: str) -> Tuple[bool, str]:
    """Validate that an IP address (after IPv4-mapped IPv6 normalization) is a safe public IP."""
    raw = (ip_str or "").strip().lower()
    if raw in CLOUD_METADATA_IPS:
        return False, f"Blocked: Target IP '{ip_str}' is a known Cloud Metadata endpoint."

    try:
        ip = normalize_ip_address(ip_str)
    except ValueError as exc:
        return False, f"Blocked: Invalid IP address representation '{ip_str}': {exc}"

    normalized_str = str(ip).lower()
    if normalized_str in CLOUD_METADATA_IPS:
        return False, f"Blocked: Target IP '{ip_str}' (normalized '{normalized_str}') is a Cloud Metadata endpoint."

    if ip.is_loopback:
        return False, f"Blocked: Loopback IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if ip.is_link_local:
        return False, f"Blocked: Link-local IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if ip.is_private:
        return False, f"Blocked: Private network IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if ip.is_multicast:
        return False, f"Blocked: Multicast IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if ip.is_unspecified:
        return False, f"Blocked: Unspecified IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if ip.is_reserved:
        return False, f"Blocked: Reserved IP '{ip_str}' (normalized '{normalized_str}') is forbidden."
    if not ip.is_global:
        return False, f"Blocked: Non-global IP '{ip_str}' (normalized '{normalized_str}') is forbidden."

    return True, ""


def resolve_ssrf_safe_target(
    url: str,
    *,
    dns_resolver: Optional[Callable[[str, int], Sequence[str]]] = None,
) -> Tuple[bool, str, str, str, int, Optional[str]]:
    """Validate URL and resolve hostname to a verified public IP for pinned connection.

    Returns `(is_safe, reason, clean_url, hostname, port, pinned_ip)`.
    """
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Blocked: Disallowed URL scheme '{parsed.scheme}'. Only http/https permitted.", "", "", 0, None

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "Blocked: Missing hostname in URL.", "", "", 0, None

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".internal") or hostname.endswith(".local"):
        return False, f"Blocked: Hostname '{hostname}' is on the SSRF blacklist.", "", hostname, 0, None

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return False, "Blocked: Invalid port in URL.", "", hostname, 0, None

    if port not in ALLOWED_PORTS:
        return (
            False,
            f"Blocked: Port {port} is restricted. Only standard web ports (80, 443, 8080, 8443) are allowed.",
            "",
            hostname,
            port,
            None,
        )

    # If hostname is already an IP literal, validate it directly before any DNS call
    try:
        ip_literal = normalize_ip_address(hostname)
        safe, reason = is_safe_ip(hostname)
        if not safe:
            return False, reason, "", hostname, port, None
        clean_url = urllib.parse.urlunparse(parsed)
        return True, "", clean_url, hostname, port, str(ip_literal)
    except ValueError:
        pass

    try:
        if dns_resolver is not None:
            resolved_ips = list(dict.fromkeys(dns_resolver(hostname, port)))
        else:
            addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            resolved_ips = list(dict.fromkeys(str(item[4][0]) for item in addr_info if item and item[4]))
    except Exception as exc:
        return False, f"DNS resolution failed for '{hostname}': {exc}", "", hostname, port, None

    if not resolved_ips:
        return False, f"DNS returned no IP addresses for '{hostname}'.", "", hostname, port, None

    validated_ips: List[str] = []
    for ip_str in resolved_ips:
        safe, reason = is_safe_ip(ip_str)
        if not safe:
            return False, reason, "", hostname, port, None
        validated_ips.append(str(normalize_ip_address(ip_str)))

    clean_url = urllib.parse.urlunparse(parsed)
    return True, "", clean_url, hostname, port, validated_ips[0]


def check_ssrf_safety(
    url: str,
    *,
    dns_resolver: Optional[Callable[[str, int], Sequence[str]]] = None,
) -> Tuple[bool, str, str, int]:
    """Validate URL and all resolved IPs against the SSRF guard.

    Returns `(is_safe, reason, clean_url, port)`.
    """
    is_safe, reason, clean_url, _hostname, port, _pinned_ip = resolve_ssrf_safe_target(
        url,
        dns_resolver=dns_resolver,
    )
    return is_safe, reason, clean_url, port


@contextmanager
def pinned_dns_resolution(hostname: str, port: int, pinned_ip: str) -> Iterator[None]:
    """Pin `socket.getaddrinfo` for `(hostname, port)` to `pinned_ip` during the outbound connection.

    Prevents DNS rebinding between `resolve_ssrf_safe_target()` and `urllib3`'s socket
    connect while preserving the original hostname for HTTP `Host` header and TLS SNI.
    """
    orig_getaddrinfo = socket.getaddrinfo
    target_host = hostname.strip().lower()
    ip_obj = ipaddress.ip_address(pinned_ip)
    family = socket.AF_INET6 if isinstance(ip_obj, ipaddress.IPv6Address) else socket.AF_INET
    sockaddr = (pinned_ip, port, 0, 0) if family == socket.AF_INET6 else (pinned_ip, port)

    def _pinned_getaddrinfo(host: Any, p: Any, *args: Any, **kwargs: Any) -> Any:
        host_str = (host.decode("utf-8", errors="ignore") if isinstance(host, bytes) else str(host or "")).strip().lower()
        if host_str == target_host:
            resolved_port = int(p) if isinstance(p, (int, str)) and str(p).isdigit() else port
            addr = (pinned_ip, resolved_port, 0, 0) if family == socket.AF_INET6 else (pinned_ip, resolved_port)
            return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", addr)]
        return orig_getaddrinfo(host, p, *args, **kwargs)

    socket.getaddrinfo = _pinned_getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = orig_getaddrinfo  # type: ignore[assignment]


def read_bounded_text(resp: Any, max_bytes: int = MAX_BODY_BYTES) -> Tuple[str, int]:
    """Read at most `max_bytes` from a streaming HTTP response and close it immediately."""
    chunks: List[bytes] = []
    total = 0
    try:
        if hasattr(resp, "iter_content"):
            try:
                stream_iter = resp.iter_content(chunk_size=CHUNK_READ_BYTES, decode_unicode=False)
            except TypeError:
                stream_iter = resp.iter_content(chunk_size=CHUNK_READ_BYTES)
            for chunk in stream_iter:
                if not chunk:
                    continue
                if isinstance(chunk, str):
                    chunk_bytes = chunk.encode("utf-8", errors="replace")
                else:
                    chunk_bytes = bytes(chunk)
                remaining = max_bytes - total
                if remaining <= 0:
                    break
                if len(chunk_bytes) > remaining:
                    chunks.append(chunk_bytes[:remaining])
                    total += remaining
                    break
                chunks.append(chunk_bytes)
                total += len(chunk_bytes)
                if total >= max_bytes:
                    break
        else:
            raw_text = getattr(resp, "text", "") or ""
            raw_bytes = raw_text.encode("utf-8", errors="replace")[:max_bytes]
            chunks.append(raw_bytes)
            total = len(raw_bytes)
    finally:
        close_fn = getattr(resp, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass

    raw = b"".join(chunks)
    encoding_attr = getattr(resp, "encoding", None)
    encoding = encoding_attr if isinstance(encoding_attr, str) and encoding_attr else "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return text, total



def _extract_excerpt(text: str, match_span: Tuple[int, int], window: int = 90) -> str:
    start = max(0, match_span[0] - window)
    end = min(len(text), match_span[1] + window)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return snippet[:240]


def classify_http_and_storefront_state(
    *,
    reachable: bool,
    http_status: Optional[int],
    final_url: str,
    body_text: str,
) -> Tuple[Optional[bool], StorefrontState]:
    """Derive `page_available` and `storefront_state` mechanically from HTTP status, URL path, and HTML."""
    if not reachable or http_status is None:
        return False, "dead"

    parsed = urllib.parse.urlparse(final_url)
    path_lower = (parsed.path or "").rstrip("/").lower()
    body_lower = (body_text or "").lower()

    # Check dead/parked domain indicators
    if http_status in (404, 410):
        return False, "dead"
    if any(
        marker in body_lower
        for marker in (
            "this domain is for sale",
            "sedoparking.com",
            "hugedomains.com",
            "godaddy.com/forsale",
            "store is currently unavailable",
            "sorry, this shop is currently unavailable",
        )
    ):
        return False, "dead"

    # Check password-protected storefront state (/password or Shopify password form)
    is_password_path = path_lower == "/password" or path_lower.endswith("/password")
    has_password_form = any(
        marker in body_lower
        for marker in (
            'action="/password"',
            "id=\"password-login\"",
            "id='password-login'",
            "shopify-section-main-password",
            "enter store using password",
        )
    )
    if is_password_path or has_password_form:
        page_avail = True if 200 <= http_status < 300 else False
        return page_avail, "password_locked"

    # Check maintenance state
    if http_status == 503 or any(
        marker in body_lower
        for marker in (
            "under scheduled maintenance",
            "we'll be back soon",
            "site is under maintenance",
            "temporarily down for maintenance",
        )
    ):
        return False, "maintenance"

    if http_status in (401, 403, 429):
        return None, "unknown"

    if http_status >= 500:
        return False, "unknown"

    if 200 <= http_status < 300:
        return True, "active"

    return False, "unknown"


# Structured Platform Rules: (platform, signal_type, regex_pattern, weight_confidence)
_PLATFORM_HTML_RULES: List[Tuple[str, str, re.Pattern[str], ConfidenceLevel]] = [
    (
        "Shopify",
        "script_or_asset:cdn.shopify.com",
        re.compile(r"(?:src|href|content)\s*=\s*[\"'][^\"']*cdn\.shopify\.com[^\"']*[\"']", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Shopify",
        "js_global:Shopify.theme",
        re.compile(r"\b(?:Shopify\.theme|window\.Shopify)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Shopify",
        "asset_path:/cdn/shop/",
        re.compile(r"(?:src|href)\s*=\s*[\"'][^\"']*/cdn/shop/(?:t|files|products)/[^\"']*[\"']", re.IGNORECASE),
        "HIGH",
    ),
    (
        "Shopify",
        "domain:myshopify.com",
        re.compile(r"[a-z0-9-]+\.myshopify\.com", re.IGNORECASE),
        "HIGH",
    ),
    (
        "WooCommerce",
        "plugin_asset:/wp-content/plugins/woocommerce/",
        re.compile(r"/wp-content/plugins/woocommerce/", re.IGNORECASE),
        "HIGH",
    ),
    (
        "WooCommerce",
        "js_var:woocommerce_params",
        re.compile(r"\b(?:woocommerce_params|wc_add_to_cart_params|wc_cart_fragments_params)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "WooCommerce",
        "endpoint:wc-ajax",
        re.compile(r"[?&]wc-ajax=[a-z0-9_]+", re.IGNORECASE),
        "HIGH",
    ),
    (
        "WooCommerce",
        "dom_class:woocommerce",
        re.compile(r"class\s*=\s*[\"'][^\"']*\bwoocommerce(?:-page|-js)?\b[^\"']*[\"']", re.IGNORECASE),
        "MEDIUM",
    ),
    (
        "Magento",
        "js_init:mage/cookies",
        re.compile(r"\b(?:mage/cookies|Magento_Ui|static/version\d+/frontend/)\b", re.IGNORECASE),
        "HIGH",
    ),
    (
        "BigCommerce",
        "asset_cdn:bigcommerce.com",
        re.compile(r"cdn\d*\.bigcommerce\.com", re.IGNORECASE),
        "HIGH",
    ),
]

# Structured App Rules distinguishing active script/widget/DOM footprints from plain text
_APP_STRUCTURAL_RULES: Dict[str, List[Tuple[str, re.Pattern[str], ConfidenceLevel]]] = {
    "Wati": [
        (
            "script_src:wati.io",
            re.compile(r"<script[^>]+src\s*=\s*[\"'][^\"']*wati\.io[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:wati",
            re.compile(r"\b(?:wati-integration|wati_widget|CreateWhatsappChatWidget)\b", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Nudgify": [
        (
            "script_src:nudgify.com",
            re.compile(r"<script[^>]+src\s*=\s*[\"'][^\"']*nudgify\.com[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:nudgify",
            re.compile(r"\b(?:nudgify-widget|nudgify\.com)\b", re.IGNORECASE),
            "MEDIUM",
        ),
    ],
    "Fera": [
        (
            "script_src:fera.ai",
            re.compile(r"<script[^>]+src\s*=\s*[\"'][^\"']*fera\.ai[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:fera",
            re.compile(r"\b(?:fera-widget|cdn\.fera\.ai)\b", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Judge.me": [
        (
            "script_or_cdn:judge.me",
            re.compile(r"(?:src|href)\s*=\s*[\"'][^\"']*(?:cdn\.)?judge\.me[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:jdgm-widget",
            re.compile(r"class\s*=\s*[\"'][^\"']*\bjdgm-(?:widget|rev-widg|preview-badge)\b[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Loox": [
        (
            "script_or_iframe:loox.io",
            re.compile(r"(?:src|href)\s*=\s*[\"'][^\"']*loox\.io[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:loox-rating",
            re.compile(r"class\s*=\s*[\"'][^\"']*\bloox-rating\b[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Smile.io": [
        (
            "script_src:smile.io",
            re.compile(r"(?:src|href)\s*=\s*[\"'][^\"']*smile\.io[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:smile-ui",
            re.compile(r"\b(?:smile-ui|smile-launcher-frame)\b", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Easysize": [
        (
            "script_src:easysize.me",
            re.compile(r"(?:src|href)\s*=\s*[\"'][^\"']*easysize\.me[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "dom_widget:easysize-widget",
            re.compile(r"\beasysize-widget\b", re.IGNORECASE),
            "HIGH",
        ),
    ],
    "Klaviyo": [
        (
            "script_src:klaviyo.com",
            re.compile(r"<script[^>]+src\s*=\s*[\"'][^\"']*klaviyo\.com[^\"']*[\"']", re.IGNORECASE),
            "HIGH",
        ),
        (
            "js_init:klaviyo",
            re.compile(r"\b(?:klaviyo\.js|_learnq\.push)\b", re.IGNORECASE),
            "MEDIUM",
        ),
    ],
}


def collect_platform_and_app_evidence(
    *,
    source_url: str,
    redirect_chain: Sequence[str],
    headers: Dict[str, Any],
    body_text: str,
) -> Tuple[str, Literal["HIGH", "MEDIUM", "LOW", "NONE"], List[str], List[str], List[VerificationEvidence]]:
    """Extract mechanical platform and installed-app evidence from headers, redirects, and HTML."""
    evidence_list: List[VerificationEvidence] = []
    signals: List[str] = []
    platform_scores: Dict[str, List[ConfidenceLevel]] = {}

    def _record_platform_ev(
        plat: str,
        sig_type: str,
        src_type: Literal["live_http_headers", "live_html_footprint"],
        excerpt: str,
        conf: ConfidenceLevel,
    ) -> None:
        platform_scores.setdefault(plat, []).append(conf)
        signals.append(f"Platform '{plat}' [{conf}]: {sig_type}")
        evidence_list.append(
            VerificationEvidence(
                verifier_version=VERIFIER_VERSION,
                source_url=source_url,
                source_type=src_type,
                supports_field="platform",
                signal_type=sig_type,
                extracted_value=plat,
                raw_excerpt=excerpt[:240],
                confidence=conf,
            )
        )

    # 1. Inspect HTTP response headers for Shopify
    lower_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    for hdr_name in ("x-shopid", "x-shopify-stage", "x-sorting-hat-shopid"):
        if hdr_name in lower_headers:
            _record_platform_ev(
                "Shopify",
                f"header:{hdr_name}",
                "live_http_headers",
                f"{hdr_name}: {lower_headers[hdr_name][:120]}",
                "HIGH",
            )

    # 2. Inspect redirect chain for *.myshopify.com
    for hop_url in redirect_chain:
        if "myshopify.com" in hop_url.lower():
            _record_platform_ev(
                "Shopify",
                "redirect_domain:myshopify.com",
                "live_http_headers",
                f"Redirect hop through {hop_url}",
                "HIGH",
            )
            break

    # 3. Inspect HTML for structural platform fingerprints
    for plat, sig_type, pattern, conf in _PLATFORM_HTML_RULES:
        match = pattern.search(body_text)
        if match:
            excerpt = _extract_excerpt(body_text, match.span())
            _record_platform_ev(plat, sig_type, "live_html_footprint", excerpt, conf)

    # Note: Plain 'wp-content' without any WooCommerce plugin/JS/DOM signal is WordPress CMS, not WooCommerce!
    # Decide winning platform & confidence
    detected_platform = "UNKNOWN"
    platform_confidence: Literal["HIGH", "MEDIUM", "LOW", "NONE"] = "NONE"
    for plat, confs in platform_scores.items():
        if "HIGH" in confs or len(confs) >= 2:
            detected_platform = plat
            platform_confidence = "HIGH"
            break
        if "MEDIUM" in confs and detected_platform == "UNKNOWN":
            detected_platform = plat
            platform_confidence = "MEDIUM"

    # 4. Inspect HTML for structural app footprints
    detected_apps: List[str] = []
    for app_name, rules in _APP_STRUCTURAL_RULES.items():
        for sig_type, pattern, conf in rules:
            match = pattern.search(body_text)
            if match:
                excerpt = _extract_excerpt(body_text, match.span())
                if app_name not in detected_apps:
                    detected_apps.append(app_name)
                signals.append(f"App '{app_name}' [{conf}]: {sig_type}")
                evidence_list.append(
                    VerificationEvidence(
                        verifier_version=VERIFIER_VERSION,
                        source_url=source_url,
                        source_type="live_html_footprint",
                        supports_field="installed_apps",
                        signal_type=sig_type,
                        extracted_value=app_name,
                        raw_excerpt=excerpt[:240],
                        confidence=conf,
                    )
                )
                break

    return detected_platform, platform_confidence, detected_apps, signals, evidence_list


class DomainVerificationService:
    """Mechanical, SSRF-pinned domain verification service."""

    def __init__(
        self,
        *,
        timeout: int = 8,
        max_redirects: int = 5,
        max_body_bytes: int = MAX_BODY_BYTES,
        dns_resolver: Optional[Callable[[str, int], Sequence[str]]] = None,
        http_get: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_body_bytes = max_body_bytes
        self._dns_resolver = dns_resolver
        self._http_get = http_get

    def verify(
        self,
        url: str,
        *,
        paths: Optional[Sequence[str]] = None,
    ) -> DomainVerificationResult:
        """Audit a candidate URL (and optional subpaths) with SSRF IP pinning and bounded 64KB reads."""
        raw_url = (url or "").strip()
        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = "https://" + raw_url

        primary = self._verify_single_url(raw_url)
        if not paths or not primary.reachable:
            return primary

        # Optional targeted subpath inspection (bounded to at most 2 extra paths)
        extra_paths = [p for p in paths if p and p != "/"][:2]
        for subpath in extra_paths:
            joined = urllib.parse.urljoin(primary.final_url.rstrip("/") + "/", subpath.lstrip("/"))
            sub_res = self._verify_single_url(joined)
            if not sub_res.reachable:
                continue
            if primary.platform == "UNKNOWN" and sub_res.platform != "UNKNOWN":
                primary.platform = sub_res.platform
                primary.platform_confidence = sub_res.platform_confidence
            for app in sub_res.detected_apps:
                if app not in primary.detected_apps:
                    primary.detected_apps.append(app)
            for sig in sub_res.signals:
                if sig not in primary.signals:
                    primary.signals.append(sig)
            existing_hashes = {ev.content_hash for ev in primary.evidence}
            for ev in sub_res.evidence:
                if ev.content_hash not in existing_hashes:
                    primary.evidence.append(ev)
                    existing_hashes.add(ev.content_hash)

        return primary

    def _verify_single_url(self, url: str) -> DomainVerificationResult:
        result = DomainVerificationResult(
            initial_url=url,
            final_url=url,
            redirect_chain=[url],
        )

        current_url = url
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )

        try:
            for hop in range(self.max_redirects + 1):
                safe, reason, clean_url, hostname, port, pinned_ip = resolve_ssrf_safe_target(
                    current_url,
                    dns_resolver=self._dns_resolver,
                )
                if not safe or not pinned_ip:
                    result.error_code = "SSRF_BLOCKED"
                    result.error_detail = f"SSRF Guard Blocked at hop {hop}: {reason}"
                    result.reachable = False
                    result.page_available = False
                    result.storefront_state = "dead"
                    return result

                result.pinned_ip = pinned_ip

                try:
                    get_fn = self._http_get or session.get
                    with pinned_dns_resolution(hostname, port, pinned_ip):
                        resp = get_fn(
                            clean_url,
                            allow_redirects=False,
                            timeout=self.timeout,
                            stream=True,
                        )
                    result.http_status = int(resp.status_code)
                    result.final_url = clean_url

                    if resp.status_code in (301, 302, 303, 307, 308):
                        headers_dict = getattr(resp, "headers", {}) or {}
                        location = headers_dict.get("Location") or headers_dict.get("location")
                        close_fn = getattr(resp, "close", None)
                        if callable(close_fn):
                            close_fn()
                        if not location:
                            break
                        next_url = urllib.parse.urljoin(clean_url, location)
                        result.redirect_chain.append(next_url)
                        current_url = next_url
                        continue

                    # Reached final HTTP response
                    result.reachable = True
                    body_text, bytes_read = read_bounded_text(resp, max_bytes=self.max_body_bytes)
                    result.bytes_read = bytes_read

                    page_avail, sf_state = classify_http_and_storefront_state(
                        reachable=True,
                        http_status=result.http_status,
                        final_url=clean_url,
                        body_text=body_text,
                    )
                    result.page_available = page_avail
                    result.storefront_state = sf_state

                    plat, plat_conf, apps, signals, ev_list = collect_platform_and_app_evidence(
                        source_url=clean_url,
                        redirect_chain=result.redirect_chain,
                        headers=dict(getattr(resp, "headers", {}) or {}),
                        body_text=body_text,
                    )
                    result.platform = plat
                    result.platform_confidence = plat_conf
                    result.detected_apps = apps
                    result.signals = signals
                    result.evidence = ev_list

                    # Emit storefront_state observation evidence
                    result.evidence.append(
                        VerificationEvidence(
                            verifier_version=VERIFIER_VERSION,
                            source_url=clean_url,
                            source_type="live_http_headers",
                            supports_field="storefront_state",
                            signal_type=f"http_status:{result.http_status}",
                            extracted_value=sf_state,
                            raw_excerpt=f"HTTP {result.http_status} on {clean_url} -> storefront_state={sf_state}",
                            confidence="HIGH",
                        )
                    )
                    return result

                except requests.exceptions.Timeout as exc:
                    result.error_code = "HTTP_TIMEOUT"
                    result.error_detail = f"HTTP request timed out: {exc}"
                    result.reachable = False
                    result.page_available = False
                    result.storefront_state = "dead"
                    return result
                except requests.exceptions.RequestException as exc:
                    result.error_code = "HTTP_REQUEST_ERROR"
                    result.error_detail = f"HTTP request failed: {exc}"
                    result.reachable = False
                    result.page_available = False
                    result.storefront_state = "dead"
                    return result
                except Exception as exc:
                    result.error_code = "VERIFIER_ERROR"
                    result.error_detail = f"Unexpected verification failure: {exc}"
                    result.reachable = False
                    result.page_available = False
                    result.storefront_state = "dead"
                    return result

            result.error_code = "MAX_REDIRECTS_EXCEEDED"
            result.error_detail = f"Exceeded maximum redirect limit ({self.max_redirects})"
            result.reachable = False
            result.page_available = False
            result.storefront_state = "dead"
            return result
        finally:
            session.close()


def verify_domain_safely(
    url: str,
    timeout: int = 8,
    max_redirects: int = 5,
    *,
    paths: Optional[Sequence[str]] = None,
    dns_resolver: Optional[Callable[[str, int], Sequence[str]]] = None,
    http_get: Optional[Callable[..., Any]] = None,
) -> DomainVerificationResult:
    """Module-level convenience wrapper around DomainVerificationService."""
    service = DomainVerificationService(
        timeout=timeout,
        max_redirects=max_redirects,
        dns_resolver=dns_resolver,
        http_get=http_get,
    )
    return service.verify(url, paths=paths)

"""
SSRF-Guarded Domain & E-Commerce Footprint Verifier
Inspects candidate websites safely:
- Validates URLs against SSRF vulnerabilities (blocks loopback, private, link-local, cloud metadata IPs).
- Re-checks every redirect hop against the SSRF guard.
- Detects live status, redirect chains, and platform/app signatures (Shopify, WooCommerce, apps).
"""

from __future__ import annotations
import socket
import ipaddress
import urllib.parse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import requests

BLOCKED_HOSTNAMES = {
    'localhost',
    'metadata.google.internal',
    'instance-data',
    'metadata.internal'
}

CLOUD_METADATA_IPS = {
    '169.254.169.254',  # AWS, GCP, Azure, DigitalOcean
    '100.100.100.200',  # Alibaba Cloud
    'fd00:ec2::254'     # AWS IPv6
}

PLATFORM_SIGNATURES = {
    'Shopify': [
        'cdn.shopify.com',
        'Shopify.theme',
        'window.Shopify',
        'myshopify.com',
        'powered-by-shopify',
        '/cdn/shop/'
    ],
    'WooCommerce': [
        'wp-content',
        'woocommerce',
        'wc-ajax',
        'wp-includes'
    ],
    'Magento': [
        'mage.cookies',
        'static/frontend',
        'skin/frontend'
    ],
    'BigCommerce': [
        'cdn11.bigcommerce.com',
        'bigcommerce.com'
    ]
}

APP_SIGNATURES = {
    'Wati': ['wati.io', 'wati-integration', 'wati_widget'],
    'Nudgify': ['nudgify.com', 'nudgify-widget'],
    'Fera': ['fera.ai', 'fera-widget', 'cdn.fera.ai'],
    'Judge.me': ['judge.me', 'jdgm-widget', 'cdn.judge.me'],
    'Loox': ['loox.io', 'loox-rating'],
    'Smile.io': ['smile.io', 'smile-ui'],
    'Easysize': ['easysize.me', 'easysize-widget'],
    'Klaviyo': ['klaviyo.com', 'klaviyo.js']
}


class DomainVerificationResult(BaseModel):
    reachable: bool = False
    initial_url: str
    final_url: str
    status_code: Optional[int] = None
    redirect_chain: List[str] = Field(default_factory=list)
    platform: str = "UNKNOWN"
    platform_confidence: str = "NONE"  # HIGH, MEDIUM, LOW, NONE
    signals: List[str] = Field(default_factory=list)
    detected_apps: List[str] = Field(default_factory=list)
    error: Optional[str] = None


def is_safe_ip(ip_str: str) -> tuple[bool, str]:
    """Inspects IP against private, loopback, link-local, and cloud metadata ranges."""
    if ip_str in CLOUD_METADATA_IPS:
        return False, f"Blocked: Target IP '{ip_str}' is a known Cloud Metadata endpoint."

    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback:
            return False, f"Blocked: Loopback IP '{ip_str}' is forbidden."
        if ip.is_private:
            return False, f"Blocked: Private network IP '{ip_str}' is forbidden."
        if ip.is_link_local:
            return False, f"Blocked: Link-local IP '{ip_str}' is forbidden."
        if ip.is_reserved:
            return False, f"Blocked: Reserved IP '{ip_str}' is forbidden."
        if ip.is_multicast:
            return False, f"Blocked: Multicast IP '{ip_str}' is forbidden."
        return True, ""
    except ValueError as e:
        return False, f"Blocked: Invalid IP address representation '{ip_str}': {e}"


def check_ssrf_safety(url: str) -> tuple[bool, str, str, int]:
    """
    Validates URL scheme, resolves hostname, and tests all resolved IPs against the SSRF guard.
    Returns (is_safe, reason, clean_url, port).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ('http', 'https'):
        return False, f"Blocked: Disallowed URL scheme '{parsed.scheme}'. Only http/https permitted.", "", 0

    hostname = (parsed.hostname or '').strip().lower()
    if not hostname:
        return False, "Blocked: Missing hostname in URL.", "", 0

    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Blocked: Hostname '{hostname}' is on the SSRF blacklist.", "", 0

    port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
    if port not in (80, 443, 8080, 8443):
        return False, f"Blocked: Port {port} is restricted. Only standard web ports (80, 443, 8080, 8443) are allowed.", "", 0

    # Resolve all IPs
    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        resolved_ips = {item[4][0] for item in addr_info}
    except Exception as e:
        return False, f"DNS resolution failed for '{hostname}': {str(e)}", "", 0

    if not resolved_ips:
        return False, f"DNS returned no IP addresses for '{hostname}'.", "", 0

    for ip_str in resolved_ips:
        safe, reason = is_safe_ip(ip_str)
        if not safe:
            return False, reason, "", 0

    clean_url = urllib.parse.urlunparse(parsed)
    return True, "", clean_url, port


def verify_domain_safely(url: str, timeout: int = 8, max_redirects: int = 5) -> DomainVerificationResult:
    """
    Safely audits a candidate website with full SSRF and redirect protection.
    Follows redirects manually and verifies each hop IP against the SSRF guard.
    """
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    result = DomainVerificationResult(
        initial_url=url,
        final_url=url,
        redirect_chain=[url]
    )

    current_url = url
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    })

    for hop in range(max_redirects + 1):
        safe, reason, clean_url, _ = check_ssrf_safety(current_url)
        if not safe:
            result.error = f"SSRF Guard Blocked at hop {hop}: {reason}"
            result.reachable = False
            return result

        try:
            # Perform GET without auto-redirects so we can check every target IP manually
            resp = session.get(clean_url, allow_redirects=False, timeout=timeout, stream=True)
            result.status_code = resp.status_code
            result.final_url = clean_url

            # If redirect status, inspect Location header
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get('Location')
                if not location:
                    break
                next_url = urllib.parse.urljoin(clean_url, location)
                result.redirect_chain.append(next_url)
                current_url = next_url
                continue

            # Reached a destination (2xx, 4xx, etc.)
            result.reachable = (resp.status_code < 500)
            
            # Read first 64KB of decoded text for technology & app signatures
            content_sample = (resp.text or '')[:65536].lower()

            # Check if any hop in the redirect chain originated from or passed through myshopify.com
            if any('myshopify.com' in u.lower() for u in result.redirect_chain):
                result.platform = 'Shopify'
                result.platform_confidence = 'HIGH'
                result.signals.append("Domain in redirect chain matches *.myshopify.com")

            # Scan platform signatures in content
            if result.platform == 'UNKNOWN':
                for platform, sigs in PLATFORM_SIGNATURES.items():
                    matched = [s for s in sigs if s.lower() in content_sample]
                    if matched:
                        result.platform = platform
                        result.platform_confidence = "HIGH" if len(matched) >= 2 else "MEDIUM"
                        result.signals.extend([f"Platform '{platform}': found '{m}'" for m in matched])
                        break
            elif result.platform == 'Shopify':
                # Add supporting content signals if present
                for sig in PLATFORM_SIGNATURES['Shopify']:
                    if sig.lower() in content_sample:
                        result.signals.append(f"Content signature: found '{sig}'")

            # Scan app signatures
            for app, sigs in APP_SIGNATURES.items():
                matched = [s for s in sigs if s.lower() in content_sample]
                if matched:
                    result.detected_apps.append(app)
                    result.signals.extend([f"App '{app}': found '{m}'" for m in matched])

            return result

        except requests.exceptions.RequestException as e:
            result.error = f"HTTP request failed: {str(e)}"
            result.reachable = False
            return result
        except Exception as e:
            result.error = f"Unexpected verification failure: {str(e)}"
            result.reachable = False
            return result

    result.error = f"Exceeded maximum redirect limit ({max_redirects})"
    return result

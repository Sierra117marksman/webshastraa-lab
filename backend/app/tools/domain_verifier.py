"""Compatibility re-export shim for `app.services.domain_verifier`."""
from __future__ import annotations

from app.services.domain_verifier import (
    ALLOWED_PORTS,
    BLOCKED_HOSTNAMES,
    CLOUD_METADATA_IPS,
    MAX_BODY_BYTES,
    VERIFIER_VERSION,
    DomainVerificationResult,
    DomainVerificationService,
    check_ssrf_safety,
    classify_http_and_storefront_state,
    collect_platform_and_app_evidence,
    is_safe_ip,
    normalize_ip_address,
    pinned_dns_resolution,
    read_bounded_text,
    resolve_ssrf_safe_target,
    verify_domain_safely,
)

__all__ = [
    "ALLOWED_PORTS",
    "BLOCKED_HOSTNAMES",
    "CLOUD_METADATA_IPS",
    "MAX_BODY_BYTES",
    "VERIFIER_VERSION",
    "DomainVerificationResult",
    "DomainVerificationService",
    "check_ssrf_safety",
    "classify_http_and_storefront_state",
    "collect_platform_and_app_evidence",
    "is_safe_ip",
    "normalize_ip_address",
    "pinned_dns_resolution",
    "read_bounded_text",
    "resolve_ssrf_safe_target",
    "verify_domain_safely",
]

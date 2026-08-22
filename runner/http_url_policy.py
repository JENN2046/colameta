"""Restricted HTTP/HTTPS URL opening for production network probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import SplitResult, urljoin, urlsplit
import urllib.error
import urllib.request


class HTTPURLPolicyError(urllib.error.URLError):
    """Raised when a URL or redirect violates the HTTP URL policy."""


@dataclass(frozen=True)
class HTTPRedirectPolicy:
    """Controls the authority and scheme changes permitted during redirects."""

    allow_cross_host: bool = False
    reject_https_downgrade: bool = True
    allow_redirects: bool = True


HostPolicy = Callable[[str], bool]


def _normalize_allowed_schemes(allowed_schemes: Iterable[str]) -> frozenset[str]:
    if isinstance(allowed_schemes, str):
        raise TypeError("allowed_schemes must be an iterable of schemes, not a string")
    normalized = frozenset(
        scheme.strip().lower()
        for scheme in allowed_schemes
        if isinstance(scheme, str) and scheme.strip()
    )
    if not normalized or not normalized.issubset({"http", "https"}):
        raise ValueError("only http and https schemes may be allowed")
    return normalized


def _normalized_hostname(parsed: SplitResult) -> str:
    hostname = parsed.hostname
    if not hostname:
        raise HTTPURLPolicyError("URL must include a hostname")
    return hostname.rstrip(".").lower()


def _normalized_authority(parsed: SplitResult) -> tuple[str, str, int]:
    """Return the scheme/host/effective-port identity for a URL."""

    scheme = parsed.scheme.lower()
    hostname = _normalized_hostname(parsed)
    try:
        explicit_port = parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPURLPolicyError("URL has an invalid port") from exc
    effective_port = explicit_port
    if effective_port is None:
        effective_port = {"http": 80, "https": 443}.get(scheme)
    if effective_port is None:
        raise HTTPURLPolicyError("URL scheme has no effective port")
    return scheme, hostname, effective_port


def _parse_and_validate_url(url: str, allowed_schemes: frozenset[str]) -> SplitResult:
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = _normalized_hostname(parsed)
        parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPURLPolicyError(f"invalid HTTP URL: {url!r}") from exc

    if not scheme or scheme not in allowed_schemes:
        raise HTTPURLPolicyError(f"URL scheme is not permitted: {scheme or '<missing>'}")
    if not hostname:
        raise HTTPURLPolicyError("URL must include a hostname")
    return parsed


def _validate_host_policy(hostname: str, host_policy: HostPolicy | None) -> None:
    if host_policy is None:
        return
    try:
        permitted = bool(host_policy(hostname))
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        raise HTTPURLPolicyError("host policy evaluation failed") from exc
    if not permitted:
        raise HTTPURLPolicyError(f"URL host is not permitted: {hostname}")


def _validate_redirect_url(
    origin_url: str,
    redirect_url: str,
    *,
    allowed_schemes: frozenset[str],
    redirect_policy: HTTPRedirectPolicy,
    host_policy: HostPolicy | None,
) -> str:
    if not redirect_policy.allow_redirects:
        raise HTTPURLPolicyError("redirect is not permitted")

    try:
        resolved_url = urljoin(origin_url, redirect_url.replace(" ", "%20"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPURLPolicyError("invalid redirect URL") from exc

    origin = _parse_and_validate_url(origin_url, allowed_schemes)
    target = _parse_and_validate_url(resolved_url, allowed_schemes)
    origin_host = _normalized_hostname(origin)
    target_host = _normalized_hostname(target)

    if (
        redirect_policy.reject_https_downgrade
        and origin.scheme.lower() == "https"
        and target.scheme.lower() == "http"
    ):
        raise HTTPURLPolicyError("HTTPS redirect downgrade to HTTP is not permitted")
    if not redirect_policy.allow_cross_host and origin_host != target_host:
        raise HTTPURLPolicyError("cross-host redirect is not permitted")
    _validate_host_policy(target_host, host_policy)
    return resolved_url


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        *,
        allowed_schemes: frozenset[str],
        redirect_policy: HTTPRedirectPolicy,
        host_policy: HostPolicy | None,
    ) -> None:
        super().__init__()
        self._allowed_schemes = allowed_schemes
        self._redirect_policy = redirect_policy
        self._host_policy = host_policy

    def http_error_302(self, req, fp, code, msg, headers):
        # Validate before urllib's built-in redirect implementation performs
        # its own partial scheme check (which still permits FTP).
        if not self._redirect_policy.allow_redirects:
            raise HTTPURLPolicyError("redirect is not permitted")
        newurl = headers.get("location") or headers.get("uri")
        if newurl:
            _validate_redirect_url(
                req.full_url,
                newurl,
                allowed_schemes=self._allowed_schemes,
                redirect_policy=self._redirect_policy,
                host_policy=self._host_policy,
            )
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request:
        resolved_url = _validate_redirect_url(
            req.full_url,
            newurl,
            allowed_schemes=self._allowed_schemes,
            redirect_policy=self._redirect_policy,
            host_policy=self._host_policy,
        )

        # Preserve the caller's request semantics.  In particular, do not let
        # urllib's default redirect behavior silently turn a POST into a GET.
        redirected = urllib.request.Request(
            resolved_url,
            data=req.data,
            headers=dict(req.headers),
            origin_req_host=req.origin_req_host,
            unverifiable=True,
            method=req.get_method(),
        )
        redirected.unredirected_hdrs = dict(req.unredirected_hdrs)
        if _normalized_authority(urlsplit(req.full_url)) != _normalized_authority(
            urlsplit(resolved_url)
        ):
            # Credentials are scoped to the effective authority, including
            # the port.  urllib stores ordinary and unredirected headers in
            # separate case-insensitive-ish mappings, so remove both forms.
            for header_map in (redirected.headers, redirected.unredirected_hdrs):
                for key in tuple(header_map):
                    if key.lower() == "authorization":
                        del header_map[key]
        if hasattr(req, "timeout"):
            redirected.timeout = req.timeout
        return redirected


def _build_restricted_opener(
    *,
    allowed_schemes: frozenset[str],
    redirect_policy: HTTPRedirectPolicy,
    host_policy: HostPolicy | None,
    allow_environment_proxy: bool = True,
) -> urllib.request.OpenerDirector:
    """Build a local opener containing only HTTP/HTTPS handlers."""

    if type(allow_environment_proxy) is not bool:
        raise TypeError("allow_environment_proxy must be a bool")
    proxy_handler = (
        urllib.request.ProxyHandler()
        if allow_environment_proxy
        else urllib.request.ProxyHandler({})
    )
    opener = urllib.request.OpenerDirector()
    for handler in (
        proxy_handler,
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        _ValidatedRedirectHandler(
            allowed_schemes=allowed_schemes,
            redirect_policy=redirect_policy,
            host_policy=host_policy,
        ),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def open_http_url(
    request_or_url: urllib.request.Request | str,
    *,
    timeout: float | int | None,
    allowed_schemes: Iterable[str],
    redirect_policy: HTTPRedirectPolicy,
    host_policy: HostPolicy | None = None,
    allow_environment_proxy: bool = True,
):
    """Open an HTTP/HTTPS URL after validating it and every redirect target.

    ``allow_environment_proxy=True`` preserves the legacy behavior of reading
    ambient ``*_proxy`` environment variables through ``ProxyHandler()``.
    ``allow_environment_proxy=False`` installs ``ProxyHandler({})`` so the
    transport destination is exactly the validated URL and never an ambient
    proxy.  The argument must be a real ``bool``; anything else raises
    ``TypeError`` so configuration strings cannot silently change semantics.
    """

    schemes = _normalize_allowed_schemes(allowed_schemes)
    if not isinstance(redirect_policy, HTTPRedirectPolicy):
        raise TypeError("redirect_policy must be an HTTPRedirectPolicy")

    if isinstance(request_or_url, urllib.request.Request):
        request = request_or_url
    elif isinstance(request_or_url, str):
        _parse_and_validate_url(request_or_url, schemes)
        request = urllib.request.Request(request_or_url)
    else:
        raise TypeError("request_or_url must be a URL string or urllib.request.Request")

    parsed = _parse_and_validate_url(request.full_url, schemes)
    _validate_host_policy(_normalized_hostname(parsed), host_policy)
    opener = _build_restricted_opener(
        allowed_schemes=schemes,
        redirect_policy=redirect_policy,
        host_policy=host_policy,
        allow_environment_proxy=allow_environment_proxy,
    )
    return opener.open(request, timeout=timeout)

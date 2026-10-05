from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from functools import lru_cache
from typing import Any

import httpx
import psycopg

from .control_store import ControlStore


@dataclass(slots=True)
class MailResult:
    provider: str
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class MailSettings:
    source: str
    enabled: bool
    provider: str | None
    from_name: str
    default_from_email: str | None
    reply_to_email: str | None
    senders: dict[str, str]
    resend_api_key: str | None = field(default=None, repr=False)


class MailError(RuntimeError):
    pass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


_VAULT_SECRET_CACHE: dict[str, tuple[float, str]] = {}


@lru_cache(maxsize=1)
def _control_store() -> ControlStore:
    # The DSN remains a root infrastructure secret. Product integration secrets
    # can live behind the control database instead of in every Vercel deployment.
    return ControlStore()


def _supabase_vault_secret(name: str) -> str | None:
    """Read a named Supabase Vault secret through a service-role-only RPC."""
    normalized = name.strip()
    if not normalized:
        return None

    now = time.monotonic()
    cached = _VAULT_SECRET_CACHE.get(normalized)
    if cached is not None and now - cached[0] < 60:
        return cached[1]

    url = _clean(os.getenv("SUPABASE_URL"))
    service_key = _clean(os.getenv("SUPABASE_SECRET_KEY")) or _clean(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not url or not service_key:
        return None

    try:
        response = httpx.post(
            f"{url.rstrip('/')}/rest/v1/rpc/open_crawl_get_vault_secret",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={"p_secret_name": normalized},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None
    if not response.is_success:
        return None

    try:
        value = _clean(response.json())
    except ValueError:
        return None
    if value:
        _VAULT_SECRET_CACHE[normalized] = (now, value)
    return value


def _env_mail_settings() -> MailSettings:
    provider = _clean(os.getenv("MAIL_PROVIDER"))
    from_name = _clean(os.getenv("OPENCRAWL_FROM_NAME")) or _clean(os.getenv("SMTP_FROM_NAME"))
    if not from_name or from_name.lower() == "internet hands":
        from_name = "OpenCrawl"
    default_from = (
        _clean(os.getenv("RESEND_FROM_EMAIL"))
        or _clean(os.getenv("INTERNET_HANDS_FROM_EMAIL"))
        or _clean(os.getenv("SMTP_FROM_EMAIL"))
    )
    return MailSettings(
        source="environment",
        enabled=True,
        provider=provider.lower() if provider else None,
        from_name=from_name,
        default_from_email=default_from,
        reply_to_email=_clean(os.getenv("MAIL_REPLY_TO")),
        senders={},
        resend_api_key=_clean(os.getenv("RESEND_API_KEY")),
    )


def _database_mail_settings(fallback: MailSettings) -> MailSettings | None:
    store = _control_store()
    if not store.configured:
        return None
    try:
        integration = store.get_platform_integration("transactional_email")
    except (RuntimeError, OSError, psycopg.Error):
        # Database-backed configuration is an enhancement, not a reason to make
        # authentication and password recovery unavailable during DB incidents.
        return None
    if integration is None:
        return None

    raw_config = integration.get("config")
    config = dict(raw_config) if isinstance(raw_config, dict) else {}
    provider = (_clean(integration.get("provider")) or fallback.provider or "resend").lower()
    from_name = _clean(config.get("from_name")) or fallback.from_name
    default_from = (
        _clean(config.get("default_from_email"))
        or _clean(config.get("from_email"))
        or fallback.default_from_email
    )
    reply_to = _clean(config.get("reply_to_email")) or fallback.reply_to_email

    raw_senders = config.get("senders")
    senders: dict[str, str] = {}
    if isinstance(raw_senders, dict):
        for key, value in raw_senders.items():
            normalized_key = _clean(key)
            normalized_value = _clean(value)
            if normalized_key and normalized_value:
                senders[normalized_key.lower()] = normalized_value

    resend_api_key = fallback.resend_api_key
    secret_name = _clean(integration.get("secret_name"))
    if provider == "resend" and secret_name:
        # OpenCrawl's application state currently lives in Neon while Supabase
        # remains the Auth/Vault boundary. Resolve Vault through the existing
        # service-role credential first; direct DB lookup remains a migration
        # fallback for deployments whose control DB is itself Supabase.
        vault_secret = _supabase_vault_secret(secret_name)
        if not vault_secret:
            try:
                vault_secret = _clean(store.get_vault_secret(secret_name))
            except (RuntimeError, OSError, psycopg.Error):
                vault_secret = None
        if vault_secret:
            resend_api_key = vault_secret

    return MailSettings(
        source="database",
        enabled=bool(integration.get("enabled")),
        provider=provider,
        from_name=from_name,
        default_from_email=default_from,
        reply_to_email=reply_to,
        senders=senders,
        resend_api_key=resend_api_key,
    )


def _mail_settings() -> MailSettings:
    fallback = _env_mail_settings()
    return _database_mail_settings(fallback) or fallback


def mail_settings_snapshot() -> dict[str, Any]:
    """Return browser-safe mail configuration metadata without secret values."""
    settings = _mail_settings()
    return {
        "source": settings.source,
        "enabled": settings.enabled,
        "provider": settings.provider,
        "from_name": settings.from_name,
        "default_from_email": settings.default_from_email,
        "reply_to_email": settings.reply_to_email,
        "senders": dict(settings.senders),
        "credential_configured": bool(settings.resend_api_key)
        if settings.provider == "resend"
        else smtp_configured(settings),
    }


def smtp_configured(settings: MailSettings | None = None) -> bool:
    settings = settings or _mail_settings()
    return settings.enabled and bool(os.getenv("SMTP_HOST") and _smtp_from_email(settings))


def resend_configured(settings: MailSettings | None = None) -> bool:
    settings = settings or _mail_settings()
    return settings.enabled and bool(settings.resend_api_key and _resend_from_email(settings))


def mail_provider(settings: MailSettings | None = None) -> str | None:
    settings = settings or _mail_settings()
    if not settings.enabled:
        return None
    preferred = (settings.provider or "").strip().lower()
    if preferred == "smtp" and smtp_configured(settings):
        return "smtp"
    if preferred == "resend" and resend_configured(settings):
        return "resend"
    # Resend is the safer default: API acceptance is observable in its event
    # dashboard, while an SMTP relay can accept a message and later drop it.
    if resend_configured(settings):
        return "resend"
    if smtp_configured(settings):
        return "smtp"
    return None


def _sender_email(settings: MailSettings, sender_key: str | None = None) -> str | None:
    if sender_key:
        selected = settings.senders.get(sender_key.strip().lower())
        if selected:
            return selected
    return settings.default_from_email


def _smtp_from_email(
    settings: MailSettings | None = None,
    sender_key: str | None = None,
) -> str | None:
    settings = settings or _mail_settings()
    if settings.source == "database":
        selected = _sender_email(settings, sender_key)
        if selected:
            return selected
    return _clean(os.getenv("SMTP_FROM_EMAIL")) or _clean(
        os.getenv("INTERNET_HANDS_FROM_EMAIL")
    )


def _resend_from_email(
    settings: MailSettings | None = None,
    sender_key: str | None = None,
) -> str | None:
    settings = settings or _mail_settings()
    if settings.source == "database":
        selected = _sender_email(settings, sender_key)
        if selected:
            return selected
    return _clean(os.getenv("RESEND_FROM_EMAIL")) or _clean(
        os.getenv("INTERNET_HANDS_FROM_EMAIL")
    )


def _from_header(
    provider: str,
    settings: MailSettings | None = None,
    sender_key: str | None = None,
) -> str:
    settings = settings or _mail_settings()
    email = (
        _smtp_from_email(settings, sender_key)
        if provider == "smtp"
        else _resend_from_email(settings, sender_key)
    )
    if not email:
        raise MailError(f"{provider} sender address is not configured")
    return formataddr((settings.from_name, email))


def _send_smtp_sync(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    settings: MailSettings,
    sender_key: str | None = None,
    reply_to: str | None = None,
) -> MailResult:
    host = os.getenv("SMTP_HOST")
    if not host:
        raise MailError("SMTP_HOST is not configured")
    try:
        port = int(os.getenv("SMTP_PORT") or ("465" if _bool_env("SMTP_USE_SSL", False) else "587"))
        timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS") or "20")
    except ValueError as exc:
        raise MailError("SMTP_PORT and SMTP_TIMEOUT_SECONDS must be numeric") from exc

    use_ssl = _bool_env("SMTP_USE_SSL", port == 465)
    starttls = _bool_env("SMTP_STARTTLS", not use_ssl)
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")

    sender_email = _smtp_from_email(settings, sender_key)
    if not sender_email:
        raise MailError("SMTP sender address is not configured")

    message = EmailMessage()
    message["From"] = _from_header("smtp", settings, sender_key)
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1])
    effective_reply_to = _clean(reply_to) or settings.reply_to_email
    if effective_reply_to:
        message["Reply-To"] = effective_reply_to
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    server: smtplib.SMTP | None = None
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        server.ehlo()
        if starttls and not use_ssl:
            server.starttls(context=context)
            server.ehlo()
        if username:
            if not password:
                raise MailError("SMTP_PASSWORD is required when SMTP_USERNAME is set")
            server.login(username, password)
        refused = server.send_message(message)
        if refused:
            raise MailError(f"SMTP server refused recipients: {', '.join(refused)}")
    except MailError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"SMTP delivery failed: {exc}") from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    return MailResult(provider="smtp", message_id=str(message["Message-ID"]))


async def _send_resend(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    settings: MailSettings,
    sender_key: str | None = None,
    reply_to: str | None = None,
) -> MailResult:
    api_key = settings.resend_api_key
    if not api_key:
        raise MailError("Resend credential is not configured")
    payload: dict[str, Any] = {
        "from": _from_header("resend", settings, sender_key),
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
    effective_reply_to = _clean(reply_to) or settings.reply_to_email
    if effective_reply_to:
        payload["reply_to"] = effective_reply_to
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise MailError(f"Resend delivery failed: {exc}") from exc
    if not response.is_success:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("error") or body.get("name") or "")
        except ValueError:
            detail = response.text
        detail = " ".join(detail.split())[:300]
        suffix = f": {detail}" if detail else ""
        raise MailError(f"Resend delivery failed with HTTP {response.status_code}{suffix}")
    body = response.json()
    return MailResult(provider="resend", message_id=str(body.get("id") or "") or None)


async def send_mail(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    sender_key: str | None = None,
    reply_to: str | None = None,
) -> MailResult:
    """Send transactional mail through DB/Vault config first, with env fallback."""
    settings = await asyncio.to_thread(_mail_settings)
    preferred = mail_provider(settings)
    resend_error: MailError | None = None
    smtp_error: MailError | None = None

    if preferred == "resend":
        try:
            return await _send_resend(
                to=to,
                subject=subject,
                text=text,
                html=html,
                settings=settings,
                sender_key=sender_key,
                reply_to=reply_to,
            )
        except MailError as exc:
            resend_error = exc

    should_try_smtp = smtp_configured(settings) and (
        preferred != "resend" or resend_error is not None
    )
    if should_try_smtp:
        try:
            return await asyncio.to_thread(
                _send_smtp_sync,
                to=to,
                subject=subject,
                text=text,
                html=html,
                settings=settings,
                sender_key=sender_key,
                reply_to=reply_to,
            )
        except MailError as exc:
            smtp_error = exc
            if not resend_configured(settings):
                raise

    if preferred != "resend" and resend_configured(settings):
        try:
            return await _send_resend(
                to=to,
                subject=subject,
                text=text,
                html=html,
                settings=settings,
                sender_key=sender_key,
                reply_to=reply_to,
            )
        except MailError as exc:
            if smtp_error is not None:
                raise MailError(
                    f"SMTP failed ({smtp_error}); Resend fallback failed ({exc})"
                ) from exc
            raise

    if resend_error is not None and smtp_error is not None:
        raise MailError(
            f"Resend failed ({resend_error}); SMTP fallback failed ({smtp_error})"
        ) from smtp_error
    if resend_error is not None:
        raise resend_error
    if smtp_error is not None:
        raise smtp_error
    raise MailError("transactional email is not configured")

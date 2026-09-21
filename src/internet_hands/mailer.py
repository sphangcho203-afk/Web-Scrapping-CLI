from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx


@dataclass(slots=True)
class MailResult:
    provider: str
    message_id: str | None = None


class MailError(RuntimeError):
    pass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and _smtp_from_email())


def resend_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and _resend_from_email())


def mail_provider() -> str | None:
    preferred = (os.getenv("MAIL_PROVIDER") or "").strip().lower()
    if preferred == "smtp" and smtp_configured():
        return "smtp"
    if preferred == "resend" and resend_configured():
        return "resend"
    # Resend is the safer default: API acceptance is observable in its event
    # dashboard, while an SMTP relay can accept a message and later drop it.
    if resend_configured():
        return "resend"
    if smtp_configured():
        return "smtp"
    return None


def _smtp_from_email() -> str | None:
    return os.getenv("SMTP_FROM_EMAIL") or os.getenv("INTERNET_HANDS_FROM_EMAIL")


def _resend_from_email() -> str | None:
    return os.getenv("RESEND_FROM_EMAIL") or os.getenv("INTERNET_HANDS_FROM_EMAIL")


def _from_header(provider: str) -> str:
    email = _smtp_from_email() if provider == "smtp" else _resend_from_email()
    if not email:
        raise MailError(f"{provider} sender address is not configured")
    name = os.getenv("SMTP_FROM_NAME") or "Internet Hands"
    return formataddr((name, email))


def _send_smtp_sync(*, to: str, subject: str, text: str, html: str) -> MailResult:
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

    sender_email = _smtp_from_email()
    if not sender_email:
        raise MailError("SMTP sender address is not configured")

    message = EmailMessage()
    message["From"] = _from_header("smtp")
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1])
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


async def _send_resend(*, to: str, subject: str, text: str, html: str) -> MailResult:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise MailError("RESEND_API_KEY is not configured")
    payload = {
        "from": _from_header("resend"),
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
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


async def send_mail(*, to: str, subject: str, text: str, html: str) -> MailResult:
    """Send transactional mail through the preferred provider with one fallback."""
    preferred = mail_provider()
    resend_error: MailError | None = None
    smtp_error: MailError | None = None

    if preferred == "resend":
        try:
            return await _send_resend(to=to, subject=subject, text=text, html=html)
        except MailError as exc:
            resend_error = exc

    should_try_smtp = smtp_configured() and (
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
            )
        except MailError as exc:
            smtp_error = exc
            if not resend_configured():
                raise

    if preferred != "resend" and resend_configured():
        try:
            return await _send_resend(to=to, subject=subject, text=text, html=html)
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

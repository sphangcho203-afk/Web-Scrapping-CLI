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
    return bool(os.getenv("SMTP_HOST") and _from_email())


def resend_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and _from_email())


def mail_provider() -> str | None:
    if smtp_configured():
        return "smtp"
    if resend_configured():
        return "resend"
    return None


def _from_email() -> str | None:
    return (
        os.getenv("SMTP_FROM_EMAIL")
        or os.getenv("INTERNET_HANDS_FROM_EMAIL")
        or os.getenv("RESEND_FROM_EMAIL")
    )


def _from_header() -> str:
    email = _from_email()
    if not email:
        raise MailError("transactional email sender is not configured")
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

    sender_email = _from_email()
    if not sender_email:
        raise MailError("SMTP sender address is not configured")

    message = EmailMessage()
    message["From"] = _from_header()
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
        "from": _from_header(),
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
        raise MailError(f"Resend delivery failed with HTTP {response.status_code}")
    body = response.json()
    return MailResult(provider="resend", message_id=str(body.get("id") or "") or None)


async def send_mail(*, to: str, subject: str, text: str, html: str) -> MailResult:
    """Send transactional mail. SMTP is preferred; Resend remains a fallback."""
    if smtp_configured():
        return await asyncio.to_thread(
            _send_smtp_sync,
            to=to,
            subject=subject,
            text=text,
            html=html,
        )
    if resend_configured():
        return await _send_resend(to=to, subject=subject, text=text, html=html)
    raise MailError("transactional email is not configured")

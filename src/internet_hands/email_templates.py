"""Shared, email-safe presentation. Callers own tokens, recipients, and delivery."""
from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

ORIGIN = "https://opencrawl.top"
FONT = "Arial,Helvetica,sans-serif"
TEXT = "#f4f1fa"
MUTED = "#b6accb"
ACCENT = "#ed38d0"
BUTTON = "#cb23b4"
LINE = "#39364e"


def _href(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Email links require an absolute HTTP or HTTPS URL")
    return escape(url, quote=True)


def paragraph(text: str) -> str:
    return (
        f'<p style="margin:0 0 22px;color:{MUTED};font:15px/1.65 {FONT};'
        f'word-wrap:break-word;overflow-wrap:anywhere">{escape(text)}</p>'
    )


def note(text: str) -> str:
    return (
        f'<div style="margin-top:28px;padding-top:22px;border-top:1px solid {LINE};'
        f'color:{MUTED};font:13px/1.65 {FONT};word-wrap:break-word">{escape(text)}</div>'
    )


def action(label: str, url: str, *, fallback: bool = False) -> str:
    href = _href(url)
    button = f"""<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px;table-layout:fixed">
<tr><td align="center" bgcolor="{BUTTON}" style="border:1px solid #f469e2;border-radius:9px;background-color:{BUTTON};background-image:linear-gradient(110deg,{BUTTON},#b717ab);mso-padding-alt:15px 22px">
<a href="{href}" style="display:block;padding:15px 22px;color:#ffffff;font:700 15px/20px {FONT};text-align:center;text-decoration:none;border-radius:9px">{escape(label)}</a>
</td></tr></table>"""
    if fallback:
        button += (
            f'<p style="margin:0;color:{MUTED};font:12px/1.7 {FONT}">'
            'Button not working? Open this link:<br>'
            f'<a href="{href}" style="color:#f17bdf;text-decoration:underline;'
            f'word-break:break-all;overflow-wrap:anywhere">{escape(url)}</a></p>'
        )
    return button


def details(rows: list[tuple[str, str]]) -> str:
    cells = []
    for label, value in rows:
        cells.append(
            f'<tr><th scope="row" width="30%" align="left" valign="top" '
            f'style="padding:13px 16px;border-bottom:1px solid {LINE};color:{MUTED};'
            f'font:400 12px/1.6 {FONT};word-wrap:break-word">{escape(label)}</th>'
            f'<td valign="top" style="padding:13px 16px;border-bottom:1px solid {LINE};'
            f'color:{TEXT};font:500 13px/1.6 {FONT};word-break:break-word;overflow-wrap:anywhere">'
            f'{escape(value)}</td></tr>'
        )
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" border="0" '
        f'style="table-layout:fixed;margin:4px 0 26px;border:1px solid {LINE};'
        'border-radius:9px;background:#111522"><tbody>' + "".join(cells) + '</tbody></table>'
    )


def verification_body(code: str | None, url: str) -> str:
    body = paragraph("Confirm this email address to finish setting up your OpenCrawl account.")
    if code is not None:
        # Keep the code as one text node so selecting/copying it yields six digits.
        body += f"""<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:4px 0 28px;table-layout:fixed">
<tr><td class="oc-email-code-panel" bgcolor="#141426" style="padding:23px 24px;border:1px solid #494066;border-radius:10px;background:#141426;background-image:linear-gradient(120deg,#19172e,#141426)">
<p style="margin:0 0 14px;color:#c7bbdc;font:11px/1.5 {FONT};letter-spacing:1.5px">VERIFICATION CODE</p>
<p class="oc-email-code" style="margin:0 0 15px;color:{TEXT};font:700 38px/1.25 Consolas,'Courier New',monospace;letter-spacing:7px">{escape(code)}</p>
<p style="margin:0;color:{MUTED};font:12px/1.6 {FONT}">Expires in 15 minutes</p>
</td></tr></table>"""
        body += paragraph("Enter the code in OpenCrawl, or use the button below.")
    else:
        body += paragraph("This verification link expires in 15 minutes.")
    return body + action("Verify email", url, fallback=True) + note(
        "If you didn’t create an OpenCrawl account, you can ignore this email."
    )


def reset_body(url: str) -> str:
    return (
        paragraph("A password reset was requested for your OpenCrawl account.")
        + paragraph("Use the button below to choose a new password. This link expires in 30 minutes.")
        + action("Reset password", url, fallback=True)
        + note("If you didn’t request this, you can ignore this email. Your password stays the same.")
    )


def verified_body() -> str:
    return (
        paragraph("Your email is verified. Your account can now create production API keys and use protected account features.")
        + action("Open your workspace", ORIGIN + "/dashboard")
    )


def login_body(method: str, when: str, ip: str, agent: str) -> str:
    return (
        paragraph("A successful sign-in to your account just occurred.")
        + details([("Method", method), ("Time", when), ("IP address", ip), ("Device", agent)])
        + action("Review account security", ORIGIN + "/dashboard/settings")
        + note("If this was not you, change your password, revoke API keys, and enable two-factor authentication.")
    )


def security_body(message: str) -> str:
    return paragraph(message) + action("Review account security", ORIGIN + "/dashboard/settings")


def payment_body(item: str, amount: str, order_id: str, payment_id: str) -> str:
    return (
        paragraph("Your purchase of " + item + " has been confirmed.")
        + details([("Amount paid", amount), ("Purchase", item), ("Order", order_id), ("Payment", payment_id)])
        + paragraph("Your OpenCrawl usage credits or plan entitlement are already active in the dashboard.")
        + action("View billing", ORIGIN + "/dashboard/billing")
    )


def change_table(product: str, rows: list[tuple[str, str, str]]) -> str:
    cells = "".join(
        '<tr>' + ''.join(
            f'<td valign="top" style="padding:12px 14px;border-top:1px solid {LINE};'
            f'color:{TEXT if index != 1 else MUTED};font:13px/1.6 {FONT};'
            f'word-break:break-word;overflow-wrap:anywhere">{escape(value)}</td>'
            for index, value in enumerate(row)
        ) + '</tr>' for row in rows
    )
    return f"""<table width="100%" cellspacing="0" cellpadding="0" border="0" style="table-layout:fixed;margin:0 0 22px;border:1px solid {LINE};border-radius:9px;background:#111522">
<caption style="padding:16px 14px;text-align:left;color:{TEXT};font:700 17px/1.4 {FONT};border:1px solid {LINE};border-bottom:0;border-radius:9px 9px 0 0;background:#1b1e2e;word-wrap:break-word">{escape(product)}</caption>
<thead><tr>{''.join(f'<th scope="col" width="{width}%" align="left" style="padding:11px 14px;color:{MUTED};font:600 11px/1.5 {FONT};background:#1b1e2e">{label}</th>' for label, width in [('Field',28),('Before',36),('After',36)])}</tr></thead>
<tbody>{cells}</tbody></table>"""


_TITLES = {
    "email_verification": "Verify your email.",
    "account_verified": "You’re verified.",
    "password_reset": "Reset your password.",
    "login_notice": "New sign-in detected.",
    "payment_confirmation": "Payment confirmed.",
    "product_change": "Product changes detected.",
    "product_test": "Your test alert is here.",
}

_PREHEADERS = {
    "email_verification": "Your verification code and link expire in 15 minutes.",
    "account_verified": "Your email is verified. Your OpenCrawl workspace is ready.",
    "password_reset": "Choose a new password. Your reset link expires in 30 minutes.",
    "login_notice": "Review the details of a successful sign-in to your account.",
    "payment_confirmation": "Your purchase is confirmed. Review your payment details.",
    "product_change": "See the before and after values from your product tracker.",
    "product_test": "A test of your tracker’s email notification settings.",
}


def render_email(title: str, body: str, *, preheader: str = "", category: str = "Account security") -> str:
    """Render trusted template HTML; all variable content must use escaped builders."""
    safe_title, safe_category = escape(title), escape(category)
    security_footer = (
        f'<p style="margin:8px 0;color:#a99dbd;font:12px/1.6 {FONT}">'
        'Never share passwords, API keys, verification codes, authenticator secrets, or recovery codes.</p>'
        if category == "Account security" else ""
    )
    return f"""<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">
<title>{safe_title}</title>
<style>
body,table,td,p,a{{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}}
table,td{{mso-table-lspace:0pt;mso-table-rspace:0pt}}
img{{border:0;outline:none;text-decoration:none}}
a:focus{{outline:2px solid #f7c3ed;outline-offset:3px}}
@media screen and (max-width:620px){{.oc-email-outer{{padding:20px 12px!important}}.oc-email-content{{padding:24px 20px!important}}.oc-email-heading{{font-size:28px!important}}.oc-email-category{{font-size:10px!important}}.oc-email-code-panel{{padding:21px 18px!important}}.oc-email-code{{font-size:32px!important;letter-spacing:5px!important}}}}
@media screen and (max-width:360px){{.oc-email-brand{{font-size:20px!important}}.oc-email-code{{font-size:29px!important;letter-spacing:4px!important}}}}
</style></head>
<body style="margin:0;padding:0;background:#090b12;color:{TEXT};font-family:{FONT}">
<div aria-hidden="true" style="display:none;font-size:1px;line-height:1px;color:#090b12;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">{escape(preheader)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#090b12" style="background:#090b12;table-layout:fixed"><tr><td class="oc-email-outer" align="center" style="padding:48px 20px">
<!--[if mso]><table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"><tr><td><![endif]-->
<table class="oc-email-frame" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#171b28" style="width:100%;max-width:600px;background:#171b28;border:1px solid {LINE};border-top:3px solid {ACCENT};border-radius:16px;box-shadow:0 18px 50px #00000044;table-layout:fixed">
<tr><td class="oc-email-content" style="padding:34px 36px 36px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="table-layout:fixed;border-bottom:1px solid {LINE};margin-bottom:32px"><tr>
<td width="40" valign="middle" style="padding:0 0 24px"><img src="{ORIGIN}/assets/opencrawl-crab.png" alt="" width="30" height="30" style="display:block;width:30px;height:30px"></td>
<td class="oc-email-brand" valign="middle" style="padding:0 0 24px;color:{TEXT};font:700 22px/1.3 {FONT};letter-spacing:-.6px">OpenCrawl</td>
<td class="oc-email-category" width="36%" align="right" valign="middle" style="padding:0 0 24px;color:{MUTED};font:12px/1.4 {FONT}">{safe_category}</td>
</tr></table>
<h1 class="oc-email-heading" style="margin:0 0 18px;color:{TEXT};font:700 34px/1.15 {FONT};letter-spacing:-1px;word-wrap:break-word">{safe_title}</h1>
{body}
</td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;table-layout:fixed"><tr><td align="center" style="padding:28px 12px 0;color:{MUTED};font:12px/1.6 {FONT}">
<p style="margin:0;color:{MUTED};font:12px/1.6 {FONT}">OpenCrawl · {safe_category}</p>{security_footer}
<p style="margin:8px 0 0;font:12px/1.6 {FONT}"><a href="{ORIGIN}/docs/security" style="color:#c4b8d8;text-decoration:underline">Security guide</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="{ORIGIN}/legal/privacy" style="color:#c4b8d8;text-decoration:underline">Privacy</a></p>
</td></tr></table>
</td></tr></table></body></html>"""


def transactional_email(event_type: str, subject: str, text: str, body: str) -> str:
    category = "Billing" if event_type == "payment_confirmation" else (
        "Product alerts" if event_type in {"product_change", "product_test"} else "Account security"
    )
    # Inbox snippets should not expose auth tokens, codes, or request metadata.
    return render_email(_TITLES.get(event_type, subject), body, preheader=_PREHEADERS.get(event_type, subject[:180]), category=category)

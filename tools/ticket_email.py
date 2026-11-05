"""Best-effort SMTP notifications for newly saved support tickets."""
from email.message import EmailMessage
from datetime import datetime, timezone
import html
import logging
import os
from pathlib import Path
import smtplib
import threading
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)
DEFAULT_RECIPIENT = "webcoordinator2@lotuselectronics.com"
LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "images" / "lotus-logo.png"
IST = ZoneInfo("Asia/Kolkata")


def _format_created_at(value) -> str:
    """Render stored UTC timestamps in an explicit Indian date/time format."""
    if not value:
        return "Not available"
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(IST).strftime("%d/%m/%Y, %I:%M %p IST")
    except (TypeError, ValueError):
        logger.warning("Invalid support ticket created_at value: %r", value)
        return "Not available"


def _port() -> int:
    try:
        value = int(os.getenv("SMTP_PORT", "587"))
        return value if 1 <= value <= 65535 else 587
    except ValueError:
        return 587


def _timeout() -> float:
    try:
        value = float(os.getenv("SMTP_TIMEOUT", "30"))
        return value if 5 <= value <= 60 else 30
    except ValueError:
        return 30


def send_ticket_email(ticket: dict) -> bool:
    """Send one notification; return False when disabled or delivery fails."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "").strip()
    recipient = os.getenv("SUPPORT_TICKET_EMAIL_TO", DEFAULT_RECIPIENT).strip()
    cc = [address.strip() for address in
          os.getenv("SUPPORT_TICKET_EMAIL_CC", "").split(",") if address.strip()]
    sender = os.getenv("SMTP_FROM", user).strip()
    if not all((host, user, password, recipient, sender)):
        logger.info("Support ticket email skipped: SMTP configuration incomplete")
        return False

    created_at_ist = _format_created_at(ticket.get("created_at"))

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = f"New Lotus support ticket: {ticket.get('ticket_id', 'unknown')}"
    message.set_content(
        "A new support ticket was raised through the Lotus chatbot.\n\n"
        f"Ticket ID: {ticket.get('ticket_id', '')}\n"
        f"Customer: {ticket.get('name', '')}\n"
        f"Phone: {ticket.get('phone', '')}\n"
        f"Issue: {ticket.get('issue', '')}\n"
        f"Status: {ticket.get('status', '')}\n"
        f"Created: {created_at_ist}\n"
    )
    safe = {key: html.escape(str(ticket.get(key, "") or "Not available"))
            for key in ("ticket_id", "name", "phone", "issue", "status")}
    safe["created_at"] = html.escape(created_at_ist)
    message.add_alternative(f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f3f8f5;font-family:Arial,Helvetica,sans-serif;color:#176b4d;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f8f5;padding:28px 12px;">
      <tr><td align="center">
        <table role="presentation" width="620" cellspacing="0" cellpadding="0" style="max-width:620px;width:100%;background:#ffffff;border:1px solid #d8eadf;border-radius:16px;overflow:hidden;">
          <tr><td align="center" style="padding:26px 28px 18px;border-bottom:4px solid #138a5b;">
            <img src="cid:lotus-logo" width="170" alt="Lotus Electronics" style="display:block;max-width:170px;height:auto;">
          </td></tr>
          <tr><td style="padding:30px 34px;">
            <div style="color:#138a5b;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">New support request</div>
            <h1 style="margin:8px 0 10px;color:#087f5b;font-size:25px;line-height:1.3;">Support Ticket {safe['ticket_id']}</h1>
            <p style="margin:0 0 24px;color:#3d765f;font-size:15px;line-height:1.6;">A customer raised a support ticket through the Lotus Electronics chatbot.</p>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #dcebe2;border-radius:12px;background:#f8fcf9;">
              <tr><td style="padding:13px 16px;color:#438067;font-size:13px;width:125px;border-bottom:1px solid #e2eee7;">Customer</td><td style="padding:13px 16px;color:#0c6848;font-weight:700;border-bottom:1px solid #e2eee7;">{safe['name']}</td></tr>
              <tr><td style="padding:13px 16px;color:#438067;font-size:13px;border-bottom:1px solid #e2eee7;">Mobile</td><td style="padding:13px 16px;color:#0c6848;font-weight:700;border-bottom:1px solid #e2eee7;">{safe['phone']}</td></tr>
              <tr><td style="padding:13px 16px;color:#438067;font-size:13px;border-bottom:1px solid #e2eee7;">Status</td><td style="padding:13px 16px;color:#087f5b;font-weight:700;border-bottom:1px solid #e2eee7;">{safe['status']}</td></tr>
              <tr><td style="padding:13px 16px;color:#438067;font-size:13px;">Created</td><td style="padding:13px 16px;color:#176b4d;">{safe['created_at']}</td></tr>
            </table>
            <div style="margin-top:22px;padding:18px 20px;border-left:5px solid #15915f;border-radius:8px;background:#edf8f1;">
              <div style="margin-bottom:7px;color:#087f5b;font-size:13px;font-weight:700;text-transform:uppercase;">Customer issue</div>
              <div style="color:#185f46;font-size:15px;line-height:1.65;white-space:pre-wrap;">{safe['issue']}</div>
            </div>
          </td></tr>
          <tr><td style="padding:17px 34px;background:#087f5b;color:#eafff2;font-size:12px;line-height:1.5;text-align:center;">Lotus Electronics · Chatbot Support Notification</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>""", subtype="html")
    try:
        message.get_body(preferencelist=("html",)).add_related(
            LOGO_PATH.read_bytes(), maintype="image", subtype="png",
            cid="<lotus-logo>", filename="lotus-logo.png", disposition="inline")
    except OSError:
        logger.warning("Lotus email logo unavailable at %s", LOGO_PATH)

    encryption = os.getenv("SMTP_ENCRYPTION", "tls").strip().casefold()
    try:
        if encryption == "ssl":
            with smtplib.SMTP_SSL(host, _port(), timeout=_timeout()) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, _port(), timeout=_timeout()) as smtp:
                smtp.ehlo()
                if encryption == "tls":
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("Support ticket email delivery failed ticket_id=%s",
                         ticket.get("ticket_id", "unknown"))
        return False


def queue_ticket_email(ticket: dict) -> None:
    """Notify in the background so SMTP cannot delay the chatbot response."""
    threading.Thread(target=send_ticket_email, args=(dict(ticket),),
                     name="ticket-email", daemon=True).start()


__all__ = ["queue_ticket_email", "send_ticket_email"]

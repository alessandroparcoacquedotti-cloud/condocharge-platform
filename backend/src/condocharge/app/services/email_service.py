from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from condocharge.core.config import Settings


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content_type: str
    content_bytes: bytes


@dataclass(frozen=True)
class EmailHealthCheckResult:
    status: str
    message: str | None = None


class EmailService:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.email_enabled)

    def _connect(self) -> smtplib.SMTP:
        try:
            server = smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20)
            server.ehlo()
            if self._settings.smtp_use_tls:
                server.starttls()
                server.ehlo()
            if self._settings.smtp_username:
                server.login(self._settings.smtp_username, self._settings.smtp_password)
            return server
        except Exception as exc:  # pragma: no cover - exercised via API error path
            raise EmailDeliveryError(str(exc)) from exc

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        if not self.enabled:
            return

        msg = EmailMessage()
        msg["From"] = self._settings.email_from
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        for attachment in attachments or []:
            maintype, _, subtype = attachment.content_type.partition("/")
            msg.add_attachment(
                attachment.content_bytes,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )

        try:
            with self._connect() as server:
                server.send_message(msg)
        except EmailDeliveryError:
            raise
        except Exception as exc:  # pragma: no cover - exercised via API error path
            raise EmailDeliveryError(str(exc)) from exc

    def check_health(self) -> EmailHealthCheckResult:
        if not self.enabled:
            return EmailHealthCheckResult(status="disabled")
        try:
            with self._connect():
                return EmailHealthCheckResult(status="ok", message="SMTP connection successful")
        except EmailDeliveryError as exc:
            return EmailHealthCheckResult(status="error", message=str(exc))

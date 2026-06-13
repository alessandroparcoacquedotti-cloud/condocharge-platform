from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from condocharge.api.deps import AdminUser
from condocharge.app.services.email_service import EmailDeliveryError, EmailService
from condocharge.app.services.email_templates import build_test_email
from condocharge.core.config import get_settings
from condocharge.schemas.billing import EmailHealthResponse, TestEmailRequest, TestEmailResponse

router = APIRouter(prefix="/admin/email", tags=["admin-email"])


@router.get("/health", response_model=EmailHealthResponse, summary="Check SMTP health for the current environment")
def email_health(admin_user: AdminUser) -> EmailHealthResponse:
    settings = get_settings()
    email_service = EmailService(settings=settings)
    result = email_service.check_health()
    return EmailHealthResponse(
        status=result.status,
        host=settings.smtp_host or None,
        port=settings.smtp_port if settings.smtp_host else None,
        use_tls=settings.smtp_use_tls if settings.smtp_host else None,
        message=result.message,
    )


@router.post("/test-send", response_model=TestEmailResponse, summary="Send or preview an SMTP test email")
def test_send_email(admin_user: AdminUser, body: TestEmailRequest) -> TestEmailResponse:
    settings = get_settings()
    email_service = EmailService(settings=settings)
    generated_at = datetime.now(tz=UTC)
    template = build_test_email(
        condominium_name=admin_user.condominium.name,
        recipient_email=body.recipient_email,
        generated_at=generated_at,
    )

    if not email_service.enabled:
        return TestEmailResponse(
            to=body.recipient_email,
            subject=template.subject,
            body_preview=template.text_body,
            html_preview=template.html_body,
            email_enabled=False,
            delivery_status="preview",
            attachments=[],
        )

    try:
        email_service.send(
            to_email=body.recipient_email,
            subject=template.subject,
            text_body=template.text_body,
            html_body=template.html_body,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Email delivery failed: {exc}") from exc

    return TestEmailResponse(
        to=body.recipient_email,
        subject=template.subject,
        body_preview=template.text_body,
        html_preview=template.html_body,
        email_enabled=True,
        delivery_status="sent",
        attachments=[],
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape

from condocharge.models.billing import ResidentBillingStatement


SUPPORT_PLACEHOLDER = "support@condocharge.local"


@dataclass(frozen=True)
class EmailTemplateContent:
    subject: str
    text_body: str
    html_body: str


def _payment_date(statement: ResidentBillingStatement) -> str:
    latest_payment_date = max((payment.received_at for payment in statement.payments), default=statement.paid_at)
    if latest_payment_date is None:
        return "-"
    return latest_payment_date.isoformat()


def _common_lines(*, condominium_name: str, statement: ResidentBillingStatement) -> list[tuple[str, str]]:
    return [
        ("Condominium", condominium_name),
        ("Resident", statement.resident.username),
        ("Resident email", statement.resident.email or "-"),
        ("Statement number", statement.statement_number),
        ("Payment reference", statement.payment_reference),
        ("Amount due", f"EUR {float(statement.amount_due_eur):.2f}"),
        ("Payment status", statement.payment_status),
        ("Period", statement.billing_period.name),
        ("Support", SUPPORT_PLACEHOLDER),
    ]


def _render_text(title: str, intro: str, lines: list[tuple[str, str]]) -> str:
    rendered = [title, "", intro, ""]
    rendered.extend(f"{label}: {value}" for label, value in lines)
    return "\n".join(rendered)


def _render_html(title: str, intro: str, lines: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>"
        for label, value in lines
    )
    return (
        "<html><body>"
        f"<h1>{escape(title)}</h1>"
        f"<p>{escape(intro)}</p>"
        f"<ul>{items}</ul>"
        "</body></html>"
    )


def build_reminder_email(*, condominium_name: str, statement: ResidentBillingStatement) -> EmailTemplateContent:
    title = f"CondoCharge reminder for {statement.statement_number}"
    intro = "This is a payment reminder for your condominium charging statement."
    lines = _common_lines(condominium_name=condominium_name, statement=statement)
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_receipt_email(*, condominium_name: str, statement: ResidentBillingStatement) -> EmailTemplateContent:
    title = f"CondoCharge receipt for {statement.statement_number}"
    intro = "This receipt confirms the latest payment recorded for your statement."
    lines = _common_lines(condominium_name=condominium_name, statement=statement) + [
        ("Amount paid", f"EUR {float(statement.amount_paid_eur):.2f}"),
        ("Payment date", _payment_date(statement)),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_statement_email(*, condominium_name: str, statement: ResidentBillingStatement) -> EmailTemplateContent:
    title = f"CondoCharge statement for {statement.statement_number}"
    intro = "This message contains your current billing statement details."
    lines = _common_lines(condominium_name=condominium_name, statement=statement) + [
        ("Statement total", f"EUR {float(statement.amount_eur):.2f}"),
        ("Generated at", statement.generated_at.isoformat()),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_test_email(*, condominium_name: str, recipient_email: str, generated_at: datetime) -> EmailTemplateContent:
    title = "CondoCharge SMTP test email"
    intro = "This is a deterministic test message from CondoCharge."
    lines = [
        ("Condominium", condominium_name),
        ("Recipient", recipient_email),
        ("Generated at", generated_at.isoformat()),
        ("Support", SUPPORT_PLACEHOLDER),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_station_available_email(
    *,
    condominium_name: str,
    resident_name: str,
    station_name: str,
    observed_at: datetime,
) -> EmailTemplateContent:
    title = f"CondoCharge station available at {condominium_name}"
    intro = "A charging station has become available."
    lines = [
        ("Condominium", condominium_name),
        ("Resident", resident_name),
        ("Station", station_name),
        ("Available at", observed_at.isoformat()),
        ("Support", SUPPORT_PLACEHOLDER),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_charging_completed_email(
    *,
    condominium_name: str,
    resident_name: str,
    station_name: str,
    end_time: datetime,
    energy_wh: int,
    total_minutes: int,
) -> EmailTemplateContent:
    title = f"CondoCharge charging completed at {condominium_name}"
    intro = "Your charging session has completed."
    lines = [
        ("Condominium", condominium_name),
        ("Resident", resident_name),
        ("Station", station_name),
        ("Completed at", end_time.isoformat()),
        ("Energy", f"{energy_wh / 1000:.3f} kWh"),
        ("Duration", f"{total_minutes} minutes"),
        ("Support", SUPPORT_PLACEHOLDER),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )


def build_resident_invitation_email(
    *,
    condominium_name: str,
    username: str,
    invitation_link: str,
    expires_at: datetime,
) -> EmailTemplateContent:
    title = "Welcome to CondoCharge"
    intro = "Your resident account is ready. Use the invitation link below to choose your password."
    lines = [
        ("Condominium", condominium_name),
        ("Username", username),
        ("Invitation link", invitation_link),
        ("Expires at", expires_at.isoformat()),
        ("Support", SUPPORT_PLACEHOLDER),
    ]
    return EmailTemplateContent(
        subject=title,
        text_body=_render_text(title, intro, lines),
        html_body=_render_html(title, intro, lines),
    )

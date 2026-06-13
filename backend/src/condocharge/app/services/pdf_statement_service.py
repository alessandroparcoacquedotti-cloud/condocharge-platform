from __future__ import annotations

from condocharge.models.billing import ResidentBillingStatement


def _pdf_escape(value: str) -> str:
    sanitized = value.encode("ascii", "replace").decode("ascii")
    return sanitized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_statement_pdf(*, condominium_name: str, statement: ResidentBillingStatement) -> bytes:
    sessions = sorted(
        statement.session_links,
        key=lambda link: (link.charging_session.end_time, link.charging_session.id),
    )
    lines = [
        "CondoCharge Statement",
        f"Condominium: {condominium_name}",
        f"Resident: {statement.resident.username}",
        f"Statement number: {statement.statement_number}",
        f"Payment reference: {statement.payment_reference}",
        f"Billing period: {statement.billing_period.name}",
        f"Range: {statement.billing_period.period_start.isoformat()} -> {statement.billing_period.period_end.isoformat()}",
        f"Sessions count: {statement.sessions_count}",
        f"Energy kWh: {float(statement.energy_kwh):.3f}",
        f"Amount EUR: {float(statement.amount_eur):.2f}",
        f"Payment status: {statement.payment_status}",
        "",
        "Included sessions:",
    ]

    for link in sessions:
        session = link.charging_session
        station_label = session.station.host if session.station is not None else f"#{session.station_id}"
        rfid_label = session.rfid_user.rfid_id if session.rfid_user is not None else "-"
        lines.append(
            f"{session.start_time.isoformat()} | {session.end_time.isoformat()} | {station_label} | {rfid_label} | {(session.energy_wh / 1000):.3f} kWh"
        )

    if not sessions:
        lines.append("No sessions included.")

    content_lines = ["BT", "/F1 10 Tf", "40 800 Td", "12 TL"]
    for index, line in enumerate(lines):
        escaped = _pdf_escape(line)
        if index == 0:
            content_lines.append(f"({escaped}) Tj")
        else:
            content_lines.append(f"T* ({escaped}) Tj")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode("ascii")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(content_stream)} >> stream\n".encode("ascii") + content_stream + b"\nendstream endobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)


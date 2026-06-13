# Billing Flow

## End-To-End Flow

1. Charging sessions are stored for stations and RFID users.
2. RFID users can be assigned to resident app users.
3. Admin creates a billing period for a date range.
4. Statement generation groups sessions by resident and computes:
   - sessions count
   - energy consumed
   - amount due using condominium energy price snapshot
5. Admin closes the period.
6. Residents can view statements and export PDFs.
7. Payments can be added manually or imported from CSV.
8. Reconciliation and reminders help close the loop operationally.

## Statement Generation

Generated statements include:

- statement number
- payment reference
- energy total
- amount
- amount paid
- amount due
- payment status
- reminder metadata

Unassigned charging sessions are tracked at the billing-period level rather than silently lost.

## Payment Handling

Payment support includes:

- append-only payment records
- partial payment handling
- payment audit trail
- reconciliation summaries

Payment status transitions:

- `unpaid`
- `partially_paid`
- `paid`
- `waived`

## CSV Import

Supported matching:

- first by `payment_reference`
- fallback by `statement_number`

Outcomes:

- matched rows create `billing_payments`
- duplicate transaction references are flagged
- unmatched rows enter `billing_unmatched_payments`
- every import run creates an import job plus row-level results

## Email Notifications

Notification types:

- `reminder`
- `receipt`
- `statement`

Behavior:

- preview-only when email is disabled
- SMTP send when enabled
- PDF attachment for reminder / receipt / statement email flows
- notification history stored with retry lineage

## Reminders

Reminder rules are condominium-specific and control:

- whether reminders are enabled
- minimum amount due
- delay after period close
- repeat window
- max reminder count

Operational flow:

- admin reviews reminder candidates
- admin runs reminder batch
- statements inside the repeat window are not re-sent


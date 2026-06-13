# Demo Data

This document defines the recommended demo dataset for screenshots, walkthroughs, and public portfolio presentation.

The goal is to present CondoCharge as a believable condominium operating shared EV charging, not as a generic sample app with placeholder names.

## Demo Condominium

- Name: `Riverview Residences`
- Context: a mid-size urban condominium with shared basement parking and two common EV charge points
- Billing model: residents are billed monthly based on imported charging sessions and the condominium energy tariff
- Energy tariff example: `EUR 0.35 / kWh`

## Demo Residents

- `Giulia Conti`
  - Unit: `A-12`
  - Role in demo: active resident with regular evening charging
- `Marco Bianchi`
  - Unit: `B-07`
  - Role in demo: second resident with lighter but consistent charging use
- `Lucia Ferraro`
  - Unit: `C-03`
  - Role in demo: newly created resident shown in the admin onboarding flow before first billing cycle

## Demo RFID Mapping

- `RFID-A12-1042` -> `Giulia Conti`
- `RFID-B07-2088` -> `Marco Bianchi`
- `RFID-C03-PEND` -> reserved for `Lucia Ferraro` during the resident-creation and RFID-assignment walkthrough

Recommended admin presentation:

- show two residents with active RFID cards
- show one resident pending assignment to make the onboarding flow realistic
- keep RFID labels short and operationally plausible rather than obviously fake placeholders

## Demo Charging Sessions

Recommended session profile for the active billing month:

- Shared stations:
  - `Garage Charger A`
  - `Garage Charger B`
- Typical charging behavior:
  - weekday evening sessions after work
  - occasional weekend top-up sessions
  - realistic durations between `1h 30m` and `2h 30m`
  - realistic energy usage between roughly `9 kWh` and `18 kWh`

Example resident activity for one billing period:

- `Giulia Conti`
  - 2 sessions
  - `14.6 kWh`
  - `17.3 kWh`
  - Total: `31.9 kWh`
- `Marco Bianchi`
  - 2 sessions
  - `9.2 kWh`
  - `11.1 kWh`
  - Total: `20.3 kWh`

Combined condominium demo total:

- Total billed charging energy: `52.2 kWh`

## Demo Billing Example

Recommended billing period:

- Period name: `June 2026`
- Coverage: `2026-06-01` to `2026-06-30`
- Tariff snapshot: `EUR 0.35 / kWh`

Example resident statements:

- `Giulia Conti`
  - Energy: `31.9 kWh`
  - Statement value: `EUR 11.17`
  - Payment status for screenshots: `partially_paid`
  - Example paid amount: `EUR 6.00`
  - Example amount due: `EUR 5.17`
- `Marco Bianchi`
  - Energy: `20.3 kWh`
  - Statement value: `EUR 7.11`
  - Payment status for screenshots: `unpaid`
  - Example amount due: `EUR 7.11`

Recommended reconciliation story:

- one matched payment for `Giulia Conti`
- one open statement for `Marco Bianchi`
- one unmatched bank-transfer row visible in the reconciliation queue

This gives screenshots a believable operational narrative:

1. residents are clearly assigned
2. sessions are attributed by RFID
3. a monthly billing period exists
4. statement totals are realistic
5. reconciliation shows both resolved and unresolved work

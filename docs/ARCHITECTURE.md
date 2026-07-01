# Architecture

## Overview

Condo Charge is a full-stack EV charging management platform for multi-tenant condominium environments.

Commercial name: Condo Charge.
Code name: `CondoCharge`.

Main layers:

- FastAPI backend for authenticated APIs and domain workflows
- React frontend for admin and resident experiences
- SQLAlchemy ORM models and Alembic migrations for persistence
- Service layer for billing, imports, reminders, PDF generation, and email delivery

## Backend

Location: `backend/src/condocharge`

Key modules:

- `api/v1`: FastAPI routers for auth, admin, resident, dashboard, billing, reconciliation, and email tools
- `app/services`: billing, email, PDF, and sync logic
- `models`: tenancy, charging, and billing persistence models
- `schemas`: request and response contracts
- `core`: configuration and security utilities
- `tools`: CLI and demo helper scripts

## Frontend

Location: `frontend/src`

Main areas:

- `pages`: admin and resident screens
- `shared/api`: typed API client and endpoint wrappers
- `shared/auth`: auth context and protected-route wrappers
- `shared/ui`: reusable controls and layout helpers

The app uses lazy-loaded route pages to reduce the size of the initial bundle.

## Data Model

Main domain groups:

- Tenancy
  - `Condominium`
  - `AppUser`
- Charging
  - `ChargingStation`
  - `RfidUser`
  - `ChargingSession`
- Billing
  - `BillingPeriod`
  - `ResidentBillingStatement`
  - `BillingPayment`
  - `BillingPaymentEvent`
  - `BillingEmailNotification`
  - `BillingUnmatchedPayment`
  - `BillingPaymentImportJob`
  - `BillingPaymentImportRow`
  - `BillingReminderRule`

## Auth And Access Control

- Access tokens include `sub`, `condominium_id`, and `role`
- Every admin/resident flow is scoped to a condominium
- API dependencies enforce role checks for admin-only and resident-only routes
- Tests cover tenant isolation and role separation

## Billing And Operations Services

The billing service owns:

- Billing period creation and generation
- Statement numbering and payment references
- Append-only payment records
- Payment import matching and unmatched queue handling
- Reminder candidate evaluation
- Reminder run batching
- Import job tracking and row-level results

Supporting services:

- `email_service.py` for SMTP and preview-mode behavior
- `email_templates.py` for deterministic plaintext/HTML output
- `pdf_statement_service.py` for statement PDF generation

## Deployment Shape

Current repository artifacts support:

- Local SQLite development
- Dockerized API and web services
- PostgreSQL container via `docker-compose.yml`

The current async import/reminder workflow uses in-process background tasks and is designed so it can later move behind a durable worker queue.

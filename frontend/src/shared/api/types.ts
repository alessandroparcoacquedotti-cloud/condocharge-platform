export type PaginationMeta = {
  total: number;
  limit: number;
  offset: number;
};

export type StationRef = {
  id: number;
  host: string;
  vendor: string;
  name: string | null;
};

export type ResidentStationRef = {
  id: number;
  name: string | null;
};

export type RfidUserRef = {
  id: number;
  rfid_id: string;
  name: string | null;
};

export type SessionResponse = {
  id: number;
  source_key: string;
  station_id: number;
  rfid_user_id: number | null;
  start_time: string;
  end_time: string;
  energy_wh: number;
  total_minutes: number;
  charging_minutes: number;
  idle_minutes: number;
  plug_type: string | null;
  created_at: string;
  updated_at: string;
  station: StationRef | null;
  rfid_user: RfidUserRef | null;
};

export type ResidentSessionResponse = {
  id: number;
  source_key: string;
  station_id: number;
  rfid_user_id: number | null;
  start_time: string;
  end_time: string;
  energy_wh: number;
  total_minutes: number;
  charging_minutes: number;
  idle_minutes: number;
  plug_type: string | null;
  created_at: string;
  updated_at: string;
  station: ResidentStationRef | null;
  rfid_user: RfidUserRef | null;
};

export type SessionListResponse = {
  items: SessionResponse[];
  pagination: PaginationMeta;
};

export type ResidentSessionListResponse = {
  items: ResidentSessionResponse[];
  pagination: PaginationMeta;
};

export type StationResponse = {
  id: number;
  host: string;
  vendor: string;
  name: string | null;
  created_at: string;
  updated_at: string;
  session_count: number;
  total_energy_wh: number;
  latest_session: SessionResponse | null;
  status: string | null;
  status_source: string | null;
  last_sync_at: string | null;
  active_session: boolean | null;
  active_session_source: string | null;
};

export type StationOccupancyResponse = {
  station_id: number;
  host: string;
  connector_status: string | null;
  computed_status: string;
  last_checked_at: string;
};

export type StationOccupancyListResponse = {
  items: StationOccupancyResponse[];
};

export type ResidentStationOccupancyResponse = {
  station_id: number;
  computed_status: string;
  last_checked_at: string;
};

export type ResidentStationOccupancyListResponse = {
  items: ResidentStationOccupancyResponse[];
};

export type StationListResponse = {
  items: StationResponse[];
  pagination: PaginationMeta;
};

export type UserResponse = {
  id: number;
  rfid_id: string;
  name: string | null;
  created_at: string;
  updated_at: string;
  session_count: number;
  total_energy_wh: number;
  latest_session: SessionResponse | null;
};

export type UserListResponse = {
  items: UserResponse[];
  pagination: PaginationMeta;
};

export type AdminNotificationLogRow = {
  id: number;
  created_at: string;
  sent_at: string | null;
  condominium_id: number;
  resident_app_user_id: number;
  resident_username: string;
  resident_email: string | null;
  notification_type: string;
  dedupe_key: string;
  status: string;
  error_message: string | null;
};

export type AdminNotificationLogListResponse = {
  items: AdminNotificationLogRow[];
  pagination: PaginationMeta;
};

export type TopUserByEnergy = {
  user_id: number;
  rfid_id: string;
  name: string | null;
  total_energy_wh: number;
  total_energy_kwh: number;
  session_count: number;
};

export type DashboardSummaryResponse = {
  total_sessions: number;
  total_energy_wh: number;
  total_energy_kwh: number;
  total_users: number;
  total_stations: number;
  latest_session: SessionResponse | null;
  top_users_by_energy: TopUserByEnergy[];
};

export type CondominiumResponse = {
  id: number;
  name: string;
};

export type AppUserResponse = {
  id: number;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  apartment_or_unit?: string | null;
  email?: string | null;
  phone_number?: string | null;
  role: "admin" | "resident" | "viewer" | string;
  is_active: boolean;
  must_change_password?: boolean;
  last_login_at?: string | null;
  condominium: CondominiumResponse;
};

export type LoginResponse = {
  token: {
    access_token: string;
    token_type: string;
    expires_in: number;
  };
  user: AppUserResponse;
};

export type ResidentCard = {
  id: number;
  rfid_id: string;
  name: string | null;
};

export type ResidentSummaryResponse = {
  from_date: string | null;
  to_date: string | null;
  total_sessions: number;
  total_energy_wh: number;
  total_energy_kwh: number;
  energy_price_eur_per_kwh: number;
  estimated_cost_eur: number;
  estimated_annual_cost_eur: number;
  latest_session: ResidentSessionResponse | null;
  cards: ResidentCard[];
  monthly_breakdown: MonthlyConsumptionPoint[];
};

export type MonthlyConsumptionPoint = {
  month: string;
  total_energy_wh: number;
  total_energy_kwh: number;
  estimated_cost_eur: number;
};

export type ResidentStationLastCharge = {
  end_time: string;
  energy_wh: number;
  total_minutes: number;
};

export type ResidentStationStatus = {
  id: number;
  name: string | null;
  known_status: string | null;
  last_sync_at: string | null;
  last_charge: ResidentStationLastCharge | null;
};

export type ResidentStationStatusListResponse = {
  items: ResidentStationStatus[];
};

export type ResidentNotificationPreferences = {
  charging_completed: boolean;
  station_available: boolean;
  station_back_online: boolean;
};

export type ResidentNotificationPreferencesUpdate = ResidentNotificationPreferences;

export type AdminResidentRow = {
  app_user_id: number;
  username: string;
  first_name?: string | null;
  last_name?: string | null;
  apartment_or_unit?: string | null;
  email?: string | null;
  phone_number?: string | null;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at?: string | null;
  invitation_status: string;
  invitation_sent_at?: string | null;
  invitation_expires_at?: string | null;
  linked_cards: ResidentCard[];
  total_energy_wh: number;
  total_energy_kwh: number;
  estimated_cost_eur: number;
};

export type CreateResidentRequest = {
  first_name: string;
  last_name: string;
  apartment_or_unit: string;
  email: string;
  phone_number?: string | null;
};

export type CreateResidentResponse = {
  resident: AppUserResponse;
  invitation_sent: boolean;
  invitation_expires_at: string;
};

export type InviteResidentResponse = {
  success: boolean;
  resident_id: number;
  invitation_expires_at: string;
};

export type InvitationStatusResponse = {
  valid: boolean;
  username?: string | null;
  condominium_name?: string | null;
  expires_at?: string | null;
};

export type InvitationCompleteResponse = {
  success: boolean;
  username: string;
};

export type ResidentProfileResponse = {
  username: string;
  first_name: string | null;
  last_name: string | null;
  apartment_or_unit: string | null;
  email: string | null;
  phone_number: string | null;
  linked_cards: ResidentCard[];
  notification_preferences: ResidentNotificationPreferences;
};

export type UpdateResidentProfileRequest = {
  email?: string | null;
  phone_number?: string | null;
};

export type AdminRfidUserRow = {
  id: number;
  rfid_id: string;
  name: string | null;
  app_user_id: number | null;
  assigned_username: string | null;
};

export type AdminSettingsResponse = {
  energy_price_eur_per_kwh: number;
};

export type BillingStatementResponse = {
  id: number;
  billing_period_id: number;
  period_name: string;
  resident_app_user_id: number;
  resident_username: string;
  statement_number: string;
  payment_reference: string;
  sessions_count: number;
  energy_kwh: number;
  amount_eur: number;
  amount_paid_eur: number;
  amount_due_eur: number;
  payment_status: "unpaid" | "partially_paid" | "paid" | "waived" | string;
  generated_at: string;
  paid_at: string | null;
  last_reminder_at: string | null;
  reminder_count: number;
};

export type BillingPaymentEventResponse = {
  id: number;
  changed_by_app_user_id: number;
  changed_by_username: string;
  old_status: string;
  new_status: string;
  note: string | null;
  created_at: string;
};

export type BillingPaymentResponse = {
  id: number;
  statement_id: number;
  amount_eur: number;
  method: "bank_transfer" | "cash" | "card" | "other" | string;
  transaction_reference: string | null;
  note: string | null;
  received_at: string;
  created_by_app_user_id: number;
  created_by_username: string;
  created_at: string;
};

export type BillingEmailNotificationResponse = {
  id: number;
  statement_id: number;
  recipient_email: string;
  notification_type: string;
  subject: string;
  body_preview: string;
  status: "preview" | "sent" | "failed" | string;
  error_message: string | null;
  sent_at: string | null;
  retry_of_notification_id: number | null;
  created_by_app_user_id: number;
  created_by_username: string;
  created_at: string;
};

export type EmailAttachmentResponse = {
  filename: string;
  content_type: string;
  size_bytes: number;
};

export type BillingStatementDetailResponse = BillingStatementResponse & {
  period_start: string;
  period_end: string;
  energy_price_eur_per_kwh_snapshot: number;
  sessions: SessionResponse[];
  payment_history: BillingPaymentEventResponse[];
  payments: BillingPaymentResponse[];
  notifications: BillingEmailNotificationResponse[];
};

export type BillingPeriodResponse = {
  id: number;
  condominium_id: number;
  name: string;
  period_start: string;
  period_end: string;
  status: "draft" | "closed" | string;
  energy_price_eur_per_kwh_snapshot: number;
  created_at: string;
  closed_at: string | null;
  statements_count: number;
  statements_total_amount_eur: number;
  unassigned_sessions_count: number;
  unassigned_energy_kwh: number;
  unassigned_amount_eur: number;
};

export type BillingPeriodDetailResponse = BillingPeriodResponse & {
  statements: BillingStatementResponse[];
};

export type SettlementSummaryResponse = {
  total_billed_eur: number;
  paid_eur: number;
  unpaid_eur: number;
  waived_eur: number;
  partially_paid_eur: number;
  collection_rate: number;
  open_periods: number;
  closed_periods: number;
};

export type ReminderPayloadResponse = {
  to: string;
  resident_username: string;
  statement_number: string;
  subject: string;
  body_preview: string;
  html_preview: string;
  amount_due_eur: number;
  payment_reference: string;
  period: string;
  email_enabled: boolean;
  delivery_status: string;
  notification_id: number;
  attachments: EmailAttachmentResponse[];
};

export type ReceiptPayloadResponse = {
  to: string;
  resident_username: string;
  statement_number: string;
  subject: string;
  body_preview: string;
  html_preview: string;
  amount_eur: number;
  amount_paid_eur: number;
  payment_reference: string;
  payment_date: string | null;
  email_enabled: boolean;
  delivery_status: string;
  notification_id: number;
  attachments: EmailAttachmentResponse[];
};

export type StatementPayloadResponse = {
  to: string;
  resident_username: string;
  statement_number: string;
  subject: string;
  body_preview: string;
  html_preview: string;
  amount_eur: number;
  amount_due_eur: number;
  payment_reference: string;
  period: string;
  email_enabled: boolean;
  delivery_status: string;
  notification_id: number;
  attachments: EmailAttachmentResponse[];
};

export type BillingReminderRuleResponse = {
  id: number;
  condominium_id: number;
  enabled: boolean;
  days_after_period_close: number;
  repeat_every_days: number;
  max_reminders: number;
  min_amount_due_eur: number;
  created_at: string;
  updated_at: string;
};

export type ReminderRunResponse = {
  candidates_count: number;
  sent_count: number;
  preview_count: number;
  skipped_count: number;
  failed_count: number;
};

export type ReconciliationRow = {
  statement_id: number;
  statement_number: string;
  payment_reference: string;
  billing_period_id: number;
  period_name: string;
  resident_app_user_id: number;
  resident_username: string;
  amount_eur: number;
  amount_paid_eur: number;
  amount_due_eur: number;
  payment_status: string;
  last_payment_at: string | null;
  reminder_count: number;
  last_reminder_at: string | null;
};

export type ReconciliationResponse = {
  rows: ReconciliationRow[];
  total_amount_eur: number;
  total_paid_eur: number;
  total_due_eur: number;
  total_received_eur: number;
  unmatched_payments_count: number;
  unmatched_payments_amount_eur: number;
  unmatched_payments: BillingUnmatchedPaymentResponse[];
};

export type BillingUnmatchedPaymentResponse = {
  id: number;
  condominium_id: number;
  raw_reference: string | null;
  amount_eur: number;
  received_at: string;
  transaction_reference: string | null;
  method: string | null;
  note: string | null;
  status: string;
  matched_statement_id: number | null;
  created_at: string;
};

export type PaymentImportResultResponse = {
  import_job_id: number;
  imported_count: number;
  duplicate_count: number;
  unmatched_count: number;
  failed_count: number;
  unmatched_payments: BillingUnmatchedPaymentResponse[];
  rows: BillingPaymentImportRowResponse[];
};

export type BillingPaymentImportRowResponse = {
  id: number;
  import_job_id: number;
  row_number: number;
  raw_payment_reference: string | null;
  raw_statement_number: string | null;
  amount_eur: number | null;
  received_at: string | null;
  transaction_reference: string | null;
  method: string | null;
  status: "matched" | "unmatched" | "duplicate" | "failed" | string;
  matched_statement_id: number | null;
  unmatched_payment_id: number | null;
  error_message: string | null;
  created_at: string;
};

export type BillingPaymentImportJobSummaryResponse = {
  id: number;
  condominium_id: number;
  filename: string;
  status: "pending" | "processing" | "completed" | "failed" | string;
  rows_total: number;
  rows_processed: number;
  progress_percent: number;
  rows_matched: number;
  rows_unmatched: number;
  rows_duplicate: number;
  rows_failed: number;
  error_message: string | null;
  created_by_app_user_id: number;
  created_by_username: string;
  created_at: string;
  completed_at: string | null;
};

export type BillingPaymentImportJobDetailResponse = BillingPaymentImportJobSummaryResponse & {
  rows: BillingPaymentImportRowResponse[];
};

export type EmailHealthResponse = {
  status: "disabled" | "ok" | "error" | string;
  host: string | null;
  port: number | null;
  use_tls: boolean | null;
  message: string | null;
};

export type TestEmailResponse = {
  to: string;
  subject: string;
  body_preview: string;
  html_preview: string;
  email_enabled: boolean;
  delivery_status: string;
  attachments: EmailAttachmentResponse[];
};

export type CostByResidentRow = {
  app_user_id: number | null;
  resident: string;
  sessions_count: number;
  energy_wh: number;
  energy_kwh: number;
  estimated_cost_eur: number;
  rfid_count: number;
};

export type AdminCostReportResponse = {
  from_date: string | null;
  to_date: string | null;
  resident_id: number | null;
  rfid_user_id: number | null;
  total_sessions: number;
  total_energy_wh: number;
  total_energy_kwh: number;
  energy_price_eur_per_kwh: number;
  total_estimated_cost_eur: number;
  by_resident: CostByResidentRow[];
};

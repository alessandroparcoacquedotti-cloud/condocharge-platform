import { createApiClient } from "./client";
import type {
  AgentStatusResponse,
  AppUserResponse,
  AdminCostReportResponse,
  AdminResidentRow,
  AdminQueueSettingsResponse,
  AdminRfidUserRow,
  AdminSettingsResponse,
  CreateResidentRequest,
  CreateResidentResponse,
  BillingEmailNotificationResponse,
  BillingPaymentImportJobDetailResponse,
  BillingPaymentImportJobSummaryResponse,
  BillingReminderRuleResponse,
  BillingUnmatchedPaymentResponse,
  BillingPaymentResponse,
  BillingPeriodDetailResponse,
  BillingPeriodResponse,
  AdminNotificationLogListResponse,
  EmailHealthResponse,
  AdminTelegramSimulationResponse,
  AdminTelegramStatusResponse,
  AdminTelegramTestSendResponse,
  PaymentImportResultResponse,
  ReceiptPayloadResponse,
  ReminderRunResponse,
  StatementPayloadResponse,
  BillingStatementDetailResponse,
  BillingStatementResponse,
  DashboardSummaryResponse,
  InvitationCompleteResponse,
  InvitationStatusResponse,
  LoginResponse,
  ReconciliationResponse,
  ReminderPayloadResponse,
  ResidentProfileResponse,
  ResidentQueueStatusResponse,
  ResidentSessionListResponse,
  TelegramLinkIssueResponse,
  TelegramLinkStatus,
  UpdateResidentProfileRequest,
  ResidentSummaryResponse,
  ResidentNotificationPreferences,
  ResidentNotificationPreferencesUpdate,
  ResidentStationOccupancyListResponse,
  ResidentStationStatusListResponse,
  SessionListResponse,
  SettlementSummaryResponse,
  StationListResponse,
  StationOccupancyListResponse,
  TestEmailResponse,
  UserListResponse,
  InviteResidentResponse,
} from "./types";

const api = createApiClient();
const dashboardApi = createApiClient({ timeoutMs: 30000 });

export type ListParams = {
  limit?: number;
  offset?: number;
};

export type SessionsParams = ListParams & {
  from_date?: string;
  to_date?: string;
  start_date?: string;
  end_date?: string;
  rfid_id?: string;
  station_id?: number;
};

export type AdminNotificationLogsParams = ListParams & {
  notification_type?: string;
  status?: string;
  resident_app_user_id?: number;
};

export const endpoints = {
  login(params: { username: string; password: string; condominium?: string }) {
    return api.postJson<LoginResponse>("/api/v1/auth/login", params);
  },
  me() {
    return api.getJson<AppUserResponse>("/api/v1/auth/me");
  },
  changePassword(params: { current_password: string; new_password: string }) {
    return api.postJson<AppUserResponse>("/api/v1/auth/change-password", params);
  },
  invitationStatus(token: string) {
    return api.getJson<InvitationStatusResponse>(`/api/v1/auth/invitation/${encodeURIComponent(token)}`);
  },
  completeInvitation(token: string, params: { password: string }) {
    return api.postJson<InvitationCompleteResponse>(`/api/v1/auth/invitation/${encodeURIComponent(token)}/complete`, params);
  },
  dashboardSummary(params: { from_date?: string; to_date?: string } = {}) {
    const search = new URLSearchParams();
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    const qs = search.toString();
    return dashboardApi.getJson<DashboardSummaryResponse>(`/api/v1/dashboard/summary${qs ? `?${qs}` : ""}`);
  },
  dashboardAgentStatus() {
    return dashboardApi.getJson<AgentStatusResponse>("/api/v1/dashboard/agent-status");
  },
  stations(params: ListParams = {}) {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    const qs = search.toString();
    return api.getJson<StationListResponse>(`/api/v1/stations${qs ? `?${qs}` : ""}`);
  },
  stationsOccupancy() {
    return api.getJson<StationOccupancyListResponse>("/api/v1/stations/occupancy");
  },
  sessions(params: SessionsParams = {}) {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    if (params.start_date) search.set("start_date", params.start_date);
    if (params.end_date) search.set("end_date", params.end_date);
    if (params.rfid_id) search.set("rfid_id", params.rfid_id);
    if (params.station_id != null) search.set("station_id", String(params.station_id));
    const qs = search.toString();
    return api.getJson<SessionListResponse>(`/api/v1/sessions${qs ? `?${qs}` : ""}`);
  },
  users(params: ListParams = {}) {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    const qs = search.toString();
    return api.getJson<UserListResponse>(`/api/v1/users${qs ? `?${qs}` : ""}`);
  },
  adminResidents() {
    return api.getJson<AdminResidentRow[]>("/api/v1/admin/residents");
  },
  createResident(params: CreateResidentRequest) {
    return api.postJson<CreateResidentResponse>("/api/v1/admin/residents", params);
  },
  inviteResident(residentId: number) {
    return api.postJson<InviteResidentResponse>("/api/v1/admin/residents/invite", { resident_id: residentId });
  },
  updateResident(
    residentId: number,
    params: {
      first_name?: string | null;
      last_name?: string | null;
      apartment_or_unit?: string | null;
      email?: string | null;
      phone_number?: string | null;
      is_active?: boolean;
    },
  ) {
    return api.patchJson<AppUserResponse>(`/api/v1/admin/residents/${residentId}`, params);
  },
  forceResidentPasswordChange(residentId: number) {
    return api.postJson<AppUserResponse>(`/api/v1/admin/residents/${residentId}/force-password-change`, {});
  },
  adminRfidUsers() {
    return api.getJson<AdminRfidUserRow[]>("/api/v1/admin/rfid-users");
  },
  assignRfidUser(rfidUserId: number, params: { app_user_id: number | null }) {
    return api.post(`/api/v1/admin/rfid-users/${rfidUserId}/assign`, {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  },
  adminSettings() {
    return api.getJson<AdminSettingsResponse>("/api/v1/admin/settings");
  },
  adminQueueSettings() {
    return api.getJson<AdminQueueSettingsResponse>("/api/v1/admin/queue/settings");
  },
  updateAdminQueueSettings(params: { queue_enabled: boolean }) {
    return api.patchJson<AdminQueueSettingsResponse>("/api/v1/admin/queue/settings", params);
  },
  updateAdminSettings(params: {
    energy_price_eur_per_kwh: number;
    telegram_station_available_enabled: boolean;
    telegram_station_busy_enabled: boolean;
    telegram_station_back_online_enabled: boolean;
    telegram_charging_completed_enabled: boolean;
    telegram_agent_offline_enabled: boolean;
    telegram_agent_recovered_enabled: boolean;
  }) {
    return api.patchJson<AdminSettingsResponse>("/api/v1/admin/settings", params);
  },
  adminTelegramStatus() {
    return api.getJson<AdminTelegramStatusResponse>("/api/v1/admin/telegram/status");
  },
  testAdminTelegram(params: { chat_id: string }) {
    return api.postJson<AdminTelegramTestSendResponse>("/api/v1/admin/telegram/test-send", params);
  },
  simulateAdminTelegram(params: { resident_app_user_id: number; notification_type: string }) {
    return api.postJson<AdminTelegramSimulationResponse>("/api/v1/admin/telegram/simulate", params);
  },
  adminNotificationLogs(params: AdminNotificationLogsParams = {}) {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    if (params.notification_type) search.set("notification_type", params.notification_type);
    if (params.status) search.set("status", params.status);
    if (params.resident_app_user_id != null) search.set("resident_app_user_id", String(params.resident_app_user_id));
    const qs = search.toString();
    return api.getJson<AdminNotificationLogListResponse>(`/api/v1/admin/notifications/logs${qs ? `?${qs}` : ""}`);
  },
  adminBillingPeriods() {
    return api.getJson<BillingPeriodResponse[]>("/api/v1/admin/billing/periods");
  },
  createBillingPeriod(params: { name: string; period_start: string; period_end: string }) {
    return api.postJson<BillingPeriodResponse>("/api/v1/admin/billing/periods", params);
  },
  adminBillingPeriod(periodId: number) {
    return api.getJson<BillingPeriodDetailResponse>(`/api/v1/admin/billing/periods/${periodId}`);
  },
  adminBillingStatement(statementId: number) {
    return api.getJson<BillingStatementDetailResponse>(`/api/v1/admin/billing/statements/${statementId}`);
  },
  generateBillingPeriod(periodId: number) {
    return api.postJson<BillingPeriodDetailResponse>(`/api/v1/admin/billing/periods/${periodId}/generate`, {});
  },
  closeBillingPeriod(periodId: number) {
    return api.postJson<BillingPeriodDetailResponse>(`/api/v1/admin/billing/periods/${periodId}/close`, {});
  },
  updateBillingStatementPaymentStatus(statementId: number, params: { payment_status: string; note?: string }) {
    return api.patchJson<BillingStatementResponse>(`/api/v1/admin/billing/statements/${statementId}/payment-status`, params);
  },
  addBillingPayment(
    statementId: number,
    params: { amount_eur: number; method: string; transaction_reference?: string | null; note?: string | null; received_at: string },
  ) {
    return api.postJson<BillingPaymentResponse>(`/api/v1/admin/billing/statements/${statementId}/payments`, params);
  },
  billingPayments(statementId: number) {
    return api.getJson<BillingPaymentResponse[]>(`/api/v1/admin/billing/statements/${statementId}/payments`);
  },
  waiveBillingStatement(statementId: number, params: { note?: string } = {}) {
    return api.patchJson<BillingStatementResponse>(`/api/v1/admin/billing/statements/${statementId}/waive`, params);
  },
  createBillingReminder(statementId: number) {
    return api.postJson<ReminderPayloadResponse>(`/api/v1/admin/billing/statements/${statementId}/reminder`, {});
  },
  createBillingReceipt(statementId: number) {
    return api.postJson<ReceiptPayloadResponse>(`/api/v1/admin/billing/statements/${statementId}/receipt`, {});
  },
  sendBillingStatement(statementId: number) {
    return api.postJson<StatementPayloadResponse>(`/api/v1/admin/billing/statements/${statementId}/send`, {});
  },
  adminReconciliation(
    params: {
      period_id?: number;
      resident_id?: number;
      payment_status?: string;
      from_date?: string;
      to_date?: string;
      received_from_date?: string;
      received_to_date?: string;
    } = {},
  ) {
    const search = new URLSearchParams();
    if (params.period_id != null) search.set("period_id", String(params.period_id));
    if (params.resident_id != null) search.set("resident_id", String(params.resident_id));
    if (params.payment_status) search.set("payment_status", params.payment_status);
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    if (params.received_from_date) search.set("received_from_date", params.received_from_date);
    if (params.received_to_date) search.set("received_to_date", params.received_to_date);
    const qs = search.toString();
    return api.getJson<ReconciliationResponse>(`/api/v1/admin/billing/reconciliation${qs ? `?${qs}` : ""}`);
  },
  async importBillingPaymentsCsv(csvText: string) {
    const res = await api.post("/api/v1/admin/billing/payments/import.csv", {
      headers: { "Content-Type": "text/csv" },
      body: csvText,
    });
    return (await res.json()) as PaymentImportResultResponse;
  },
  async importBillingPaymentsCsvUpload(file: File) {
    const form = new FormData();
    form.append("file", file);
    const res = await api.post("/api/v1/admin/billing/payments/import", {
      body: form,
    });
    return (await res.json()) as PaymentImportResultResponse;
  },
  billingPaymentImportJobs() {
    return api.getJson<BillingPaymentImportJobSummaryResponse[]>("/api/v1/admin/billing/payments/import-jobs");
  },
  billingPaymentImportJob(jobId: number) {
    return api.getJson<BillingPaymentImportJobDetailResponse>(`/api/v1/admin/billing/payments/import-jobs/${jobId}`);
  },
  async exportImportJobErrorsCsv(jobId: number) {
    return await api.get(`/api/v1/admin/billing/payments/import-jobs/${jobId}/errors.csv`);
  },
  matchUnmatchedPayment(unmatchedPaymentId: number, params: { statement_id: number }) {
    return api.postJson<BillingUnmatchedPaymentResponse>(`/api/v1/admin/billing/unmatched-payments/${unmatchedPaymentId}/match`, params);
  },
  ignoreUnmatchedPayment(unmatchedPaymentId: number, params: { note?: string } = {}) {
    return api.patchJson<BillingUnmatchedPaymentResponse>(`/api/v1/admin/billing/unmatched-payments/${unmatchedPaymentId}/ignore`, params);
  },
  retryBillingNotification(notificationId: number) {
    return api.postJson<BillingEmailNotificationResponse>(`/api/v1/admin/billing/notifications/${notificationId}/retry`, {});
  },
  billingReminderRule() {
    return api.getJson<BillingReminderRuleResponse>("/api/v1/admin/billing/reminders/rule");
  },
  updateBillingReminderRule(params: {
    enabled: boolean;
    days_after_period_close: number;
    repeat_every_days: number;
    max_reminders: number;
    min_amount_due_eur: number;
  }) {
    return api.putJson<BillingReminderRuleResponse>("/api/v1/admin/billing/reminders/rule", params);
  },
  reminderCandidates() {
    return api.getJson<BillingStatementResponse[]>("/api/v1/admin/billing/reminders/candidates");
  },
  runReminders() {
    return api.postJson<ReminderRunResponse>("/api/v1/admin/billing/reminders/run", {});
  },
  async exportBillingPeriodCsv(periodId: number) {
    return await api.get(`/api/v1/admin/billing/periods/${periodId}/export.csv`);
  },
  async exportAdminBillingStatementPdf(statementId: number) {
    return await api.get(`/api/v1/admin/billing/statements/${statementId}/export.pdf`);
  },
  adminSettlementSummary() {
    return api.getJson<SettlementSummaryResponse>("/api/v1/admin/billing/settlement/summary");
  },
  adminEmailHealth() {
    return api.getJson<EmailHealthResponse>("/api/v1/admin/email/health");
  },
  testAdminEmail(params: { recipient_email: string }) {
    return api.postJson<TestEmailResponse>("/api/v1/admin/email/test-send", params);
  },
  residentSummary(params: { from_date?: string; to_date?: string } = {}) {
    const search = new URLSearchParams();
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    const qs = search.toString();
    return api.getJson<ResidentSummaryResponse>(`/api/v1/resident/summary${qs ? `?${qs}` : ""}`);
  },
  residentSessions(params: ListParams & { from_date?: string; to_date?: string } = {}) {
    const search = new URLSearchParams();
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    const qs = search.toString();
    return api.getJson<ResidentSessionListResponse>(`/api/v1/resident/sessions${qs ? `?${qs}` : ""}`);
  },
  residentStationsStatus() {
    return api.getJson<ResidentStationStatusListResponse>("/api/v1/resident/stations");
  },
  residentQueueStatus() {
    return api.getJson<ResidentQueueStatusResponse>("/api/v1/resident/queue");
  },
  joinResidentQueue() {
    return api.postJson<ResidentQueueStatusResponse>("/api/v1/resident/queue", {});
  },
  leaveResidentQueue() {
    return api.deleteJson<ResidentQueueStatusResponse>("/api/v1/resident/queue");
  },
  residentStationsOccupancy() {
    return api.getJson<ResidentStationOccupancyListResponse>("/api/v1/resident/stations/occupancy");
  },
  residentNotificationPreferences() {
    return api.getJson<ResidentNotificationPreferences>("/api/v1/resident/notifications/preferences");
  },
  updateResidentNotificationPreferences(params: ResidentNotificationPreferencesUpdate) {
    return api.putJson<ResidentNotificationPreferences>("/api/v1/resident/notifications/preferences", params);
  },
  residentProfile() {
    return api.getJson<ResidentProfileResponse>("/api/v1/resident/profile");
  },
  updateResidentProfile(params: UpdateResidentProfileRequest) {
    return api.patchJson<ResidentProfileResponse>("/api/v1/resident/profile", params);
  },
  issueResidentTelegramLink() {
    return api.postJson<TelegramLinkIssueResponse>("/api/v1/resident/telegram/link", {});
  },
  unlinkResidentTelegram() {
    return api.deleteJson<TelegramLinkStatus>("/api/v1/resident/telegram/link");
  },
  residentBillingStatements() {
    return api.getJson<BillingStatementResponse[]>("/api/v1/resident/billing/statements");
  },
  residentBillingStatement(statementId: number) {
    return api.getJson<BillingStatementDetailResponse>(`/api/v1/resident/billing/statements/${statementId}`);
  },
  async exportResidentBillingStatementPdf(statementId: number) {
    return await api.get(`/api/v1/resident/billing/statements/${statementId}/export.pdf`);
  },
  adminCostReport(params: { resident_id?: number; rfid_user_id?: number; from_date?: string; to_date?: string } = {}) {
    const search = new URLSearchParams();
    if (params.resident_id != null) search.set("resident_id", String(params.resident_id));
    if (params.rfid_user_id != null) search.set("rfid_user_id", String(params.rfid_user_id));
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    const qs = search.toString();
    return api.getJson<AdminCostReportResponse>(`/api/v1/admin/reports/costs${qs ? `?${qs}` : ""}`);
  },
  async adminCostReportCsv(params: { resident_id?: number; rfid_user_id?: number; from_date?: string; to_date?: string } = {}) {
    const search = new URLSearchParams();
    if (params.resident_id != null) search.set("resident_id", String(params.resident_id));
    if (params.rfid_user_id != null) search.set("rfid_user_id", String(params.rfid_user_id));
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    const qs = search.toString();
    return await api.get(`/api/v1/admin/reports/costs/export.csv${qs ? `?${qs}` : ""}`);
  },
};

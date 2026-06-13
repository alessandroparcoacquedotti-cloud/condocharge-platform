import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { BillingPeriodDetailResponse, BillingPeriodResponse, BillingStatementDetailResponse, BillingStatementResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatCurrencyEur, formatDateTime, formatKwhFromWh, formatNumber } from "../shared/ui";

function isoDateTime(value: string) {
  return `${value}T00:00:00Z`;
}

export default function AdminBillingPage() {
  const periodsFetcher = useMemo(() => () => endpoints.adminBillingPeriods(), []);
  const periodsQuery = useQuery<BillingPeriodResponse[]>(periodsFetcher);

  const [selectedPeriodId, setSelectedPeriodId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [selectedStatementId, setSelectedStatementId] = useState<number | null>(null);
  const [paymentNote, setPaymentNote] = useState("");
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"bank_transfer" | "cash" | "card" | "other">("bank_transfer");
  const [paymentTxRef, setPaymentTxRef] = useState("");
  const [paymentReceivedAt, setPaymentReceivedAt] = useState("");
  const [paymentRecordNote, setPaymentRecordNote] = useState("");
  const [reminderPayload, setReminderPayload] = useState<string | null>(null);
  const [receiptPayload, setReceiptPayload] = useState<string | null>(null);
  const [statementPayload, setStatementPayload] = useState<string | null>(null);
  const [savingPayment, setSavingPayment] = useState(false);
  const [savingReminder, setSavingReminder] = useState(false);
  const [retryingNotificationId, setRetryingNotificationId] = useState<number | null>(null);

  useEffect(() => {
    if (!selectedPeriodId && periodsQuery.data?.length) {
      setSelectedPeriodId(periodsQuery.data[0].id);
    }
  }, [periodsQuery.data, selectedPeriodId]);

  const detailFetcher = useMemo(
    () => () => (selectedPeriodId ? endpoints.adminBillingPeriod(selectedPeriodId) : Promise.resolve(null)),
    [selectedPeriodId],
  );
  const detailQuery = useQuery<BillingPeriodDetailResponse | null>(detailFetcher);

  const statementDetailFetcher = useMemo(
    () => () => (selectedStatementId ? endpoints.adminBillingStatement(selectedStatementId) : Promise.resolve(null)),
    [selectedStatementId],
  );
  const statementDetailQuery = useQuery<BillingStatementDetailResponse | null>(statementDetailFetcher);

  useEffect(() => {
    if (!detailQuery.data?.statements.length) {
      setSelectedStatementId(null);
      return;
    }
    if (!selectedStatementId || !detailQuery.data.statements.some((statement) => statement.id === selectedStatementId)) {
      setSelectedStatementId(detailQuery.data.statements[0].id);
    }
  }, [detailQuery.data, selectedStatementId]);

  async function handleCreatePeriod(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setActionError(null);
    try {
      const created = await endpoints.createBillingPeriod({
        name: name.trim(),
        period_start: isoDateTime(periodStart),
        period_end: `${periodEnd}T23:59:59Z`,
      });
      setName("");
      setPeriodStart("");
      setPeriodEnd("");
      setSelectedPeriodId(created.id);
      periodsQuery.refetch();
      detailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile creare il periodo");
    } finally {
      setSubmitting(false);
    }
  }

  async function runPeriodAction(action: "generate" | "close") {
    if (!selectedPeriodId) return;
    setActionError(null);
    try {
      if (action === "generate") {
        await endpoints.generateBillingPeriod(selectedPeriodId);
      } else {
        await endpoints.closeBillingPeriod(selectedPeriodId);
      }
      periodsQuery.refetch();
      detailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : `Impossibile eseguire l'azione: ${action}`);
    }
  }

  async function updatePaymentStatus(statement: BillingStatementResponse, payment_status: string) {
    setActionError(null);
    try {
      await endpoints.updateBillingStatementPaymentStatus(statement.id, { payment_status, note: paymentNote.trim() || undefined });
      setPaymentNote("");
      detailQuery.refetch();
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare lo stato");
    }
  }

  async function waiveStatement(statementId: number) {
    setActionError(null);
    try {
      await endpoints.waiveBillingStatement(statementId, { note: paymentNote.trim() || undefined });
      setPaymentNote("");
      detailQuery.refetch();
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile annullare il documento");
    }
  }

  async function addPayment(statementId: number) {
    setSavingPayment(true);
    setActionError(null);
    try {
      const amount = Number(paymentAmount);
      const receivedAtIso = paymentReceivedAt ? new Date(paymentReceivedAt).toISOString() : new Date().toISOString();
      await endpoints.addBillingPayment(statementId, {
        amount_eur: amount,
        method: paymentMethod,
        transaction_reference: paymentTxRef.trim() || null,
        note: paymentRecordNote.trim() || null,
        received_at: receivedAtIso,
      });
      setPaymentAmount("");
      setPaymentTxRef("");
      setPaymentReceivedAt("");
      setPaymentRecordNote("");
      detailQuery.refetch();
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiungere il pagamento");
    } finally {
      setSavingPayment(false);
    }
  }

  async function createReminder(statementId: number) {
    setSavingReminder(true);
    setActionError(null);
    setReminderPayload(null);
    try {
      const payload = await endpoints.createBillingReminder(statementId);
      setReminderPayload(JSON.stringify(payload, null, 2));
      detailQuery.refetch();
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile creare i metadati notifica");
    } finally {
      setSavingReminder(false);
    }
  }

  async function sendReceipt(statementId: number) {
    setSavingReminder(true);
    setActionError(null);
    setReceiptPayload(null);
    try {
      const payload = await endpoints.createBillingReceipt(statementId);
      setReceiptPayload(JSON.stringify(payload, null, 2));
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile inviare la ricevuta");
    } finally {
      setSavingReminder(false);
    }
  }

  async function sendStatement(statementId: number) {
    setSavingReminder(true);
    setActionError(null);
    setStatementPayload(null);
    try {
      const payload = await endpoints.sendBillingStatement(statementId);
      setStatementPayload(JSON.stringify(payload, null, 2));
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile inviare il documento");
    } finally {
      setSavingReminder(false);
    }
  }

  async function retryNotification(notificationId: number) {
    setRetryingNotificationId(notificationId);
    setActionError(null);
    try {
      const payload = await endpoints.retryBillingNotification(notificationId);
      setReceiptPayload(JSON.stringify(payload, null, 2));
      statementDetailQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile riprovare l'invio");
    } finally {
      setRetryingNotificationId(null);
    }
  }

  async function exportCsv() {
    if (!selectedPeriodId) return;
    setExporting(true);
    try {
      const res = await endpoints.exportBillingPeriodCsv(selectedPeriodId);
      if (!res.ok) throw new Error(`Esportazione non riuscita (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `billing_period_${selectedPeriodId}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  async function exportStatementPdf() {
    if (!selectedStatementId) return;
    setExporting(true);
    try {
      const res = await endpoints.exportAdminBillingStatementPdf(selectedStatementId);
      if (!res.ok) throw new Error(`Esportazione non riuscita (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `statement_${selectedStatementId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div>
      <PageHead title="Addebiti" subtitle="Gestione periodi, documenti e strumenti operativi (facoltativi)" />

      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {periodsQuery.loading ? <LoadingState label="Caricamento periodi…" /> : null}
      {periodsQuery.error ? <ErrorState title="Impossibile caricare i periodi" message={periodsQuery.error} onRetry={periodsQuery.refetch} /> : null}

      <div className="grid">
        <div className="card" style={{ gridColumn: "span 4" }}>
          <div className="card-title">Crea periodo</div>
          <form className="auth-form" onSubmit={handleCreatePeriod}>
            <label className="auth-label">
              Nome
              <input className="auth-input" value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label className="auth-label">
              Inizio periodo
              <input className="auth-input" type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} required />
            </label>
            <label className="auth-label">
              Fine periodo
              <input className="auth-input" type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} required />
            </label>
            <button className="btn" type="submit" disabled={submitting || !name.trim() || !periodStart || !periodEnd}>
              {submitting ? "Creazione…" : "Crea periodo"}
            </button>
          </form>
        </div>

        <div className="card" style={{ gridColumn: "span 8" }}>
          <div className="card-title">Periodi</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Intervallo</th>
                  <th>Stato</th>
                  <th>Documenti</th>
                  <th>kWh non assegnati</th>
                </tr>
              </thead>
              <tbody>
                {(periodsQuery.data ?? []).map((period) => (
                  <tr
                    key={period.id}
                    onClick={() => setSelectedPeriodId(period.id)}
                    style={{ cursor: "pointer", opacity: selectedPeriodId === period.id ? 1 : 0.85 }}
                  >
                    <td style={{ fontWeight: 700 }}>{period.name}</td>
                    <td>{formatDateTime(period.period_start)} - {formatDateTime(period.period_end)}</td>
                    <td>{period.status}</td>
                    <td>{period.statements_count}</td>
                    <td>{formatNumber(period.unassigned_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {detailQuery.loading ? <LoadingState label="Caricamento dettaglio…" /> : null}
      {detailQuery.error ? <ErrorState title="Impossibile caricare il dettaglio" message={detailQuery.error} onRetry={detailQuery.refetch} /> : null}

      {detailQuery.data ? (
        <div className="grid" style={{ marginTop: 12 }}>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Periodo selezionato</div>
            <div className="metric" style={{ fontSize: 20 }}>{detailQuery.data.name}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {detailQuery.data.status} • {formatCurrencyEur(detailQuery.data.energy_price_eur_per_kwh_snapshot, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}/kWh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale documenti</div>
            <div className="metric">{formatCurrencyEur(detailQuery.data.statements_total_amount_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Consumi non assegnati</div>
            <div className="metric">{formatNumber(detailQuery.data.unassigned_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {detailQuery.data.unassigned_sessions_count} ricariche • {formatCurrencyEur(detailQuery.data.unassigned_amount_eur)}
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Azioni</div>
            <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
              <button className="btn" type="button" disabled={detailQuery.data.status === "closed"} onClick={() => runPeriodAction("generate")}>
                Genera
              </button>
              <button className="btn" type="button" disabled={detailQuery.data.status === "closed"} onClick={() => runPeriodAction("close")}>
                Chiudi
              </button>
              <button className="btn" type="button" disabled={exporting} onClick={exportCsv}>
                {exporting ? "Esportazione…" : "Esporta CSV"}
              </button>
            </div>
          </div>

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Documenti per residente</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Documento</th>
                    <th>Residente</th>
                    <th>Ricariche</th>
                    <th>kWh</th>
                    <th>Importo</th>
                    <th>Stato</th>
                  </tr>
                </thead>
                <tbody>
                  {detailQuery.data.statements.map((statement) => (
                    <tr key={statement.id} onClick={() => setSelectedStatementId(statement.id)} style={{ cursor: "pointer" }}>
                      <td style={{ fontWeight: 700 }}>{statement.statement_number}</td>
                      <td style={{ fontWeight: 700 }}>{statement.resident_username}</td>
                      <td>{statement.sessions_count}</td>
                      <td>{formatNumber(statement.energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                      <td>{formatCurrencyEur(statement.amount_eur)}</td>
                      <td>
                        <select
                          className="auth-input"
                          value={statement.payment_status}
                          onChange={(e) => updatePaymentStatus(statement, e.target.value)}
                        >
                          <option value="unpaid">Non pagato</option>
                          <option value="paid">Pagato</option>
                          <option value="waived">Annullato</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                  {!detailQuery.data.statements.length ? (
                    <tr>
                      <td colSpan={6} className="muted">Nessun documento generato.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          {statementDetailQuery.loading ? <LoadingState label="Caricamento dettaglio documento…" /> : null}
          {statementDetailQuery.error ? <ErrorState title="Impossibile caricare il dettaglio" message={statementDetailQuery.error} onRetry={statementDetailQuery.refetch} /> : null}

          {statementDetailQuery.data ? (
            (() => {
              const statementDetail = statementDetailQuery.data;
              return (
            <>
              <div className="card" style={{ gridColumn: "span 4" }}>
                <div className="card-title">Dettaglio documento</div>
                <div style={{ display: "grid", gap: 8 }}>
                  <div><strong>{statementDetail.statement_number}</strong></div>
                  <div className="muted">Riferimento: {statementDetail.payment_reference}</div>
                  <div className="muted">Residente: {statementDetail.resident_username}</div>
                  <div className="muted">Stato: {statementDetail.payment_status}</div>
                  <div className="muted">Totale: {formatCurrencyEur(statementDetail.amount_eur)}</div>
                  <div className="muted">Registrato: {formatCurrencyEur(statementDetail.amount_paid_eur)}</div>
                  <div className="muted">Residuo: {formatCurrencyEur(statementDetail.amount_due_eur)}</div>
                  <div className="muted">
                    Notifiche: {statementDetail.reminder_count} • Ultima: {formatDateTime(statementDetail.last_reminder_at)}
                  </div>
                  <div className="muted">Invio email: {statementDetail.notifications[0]?.status ?? "nessuna notifica"}</div>
                  <button className="btn" type="button" disabled={exporting} onClick={exportStatementPdf}>
                    {exporting ? "Esportazione…" : "Esporta PDF"}
                  </button>
                  <button className="btn" type="button" disabled={savingReminder} onClick={() => createReminder(statementDetail.id)}>
                    {savingReminder ? "Creazione…" : "Crea metadati notifica"}
                  </button>
                  <button className="btn" type="button" disabled={savingReminder} onClick={() => sendStatement(statementDetail.id)}>
                    {savingReminder ? "Invio…" : "Invia documento"}
                  </button>
                  <button className="btn" type="button" disabled={savingReminder || statementDetail.payment_status !== "paid"} onClick={() => sendReceipt(statementDetail.id)}>
                    {savingReminder ? "Invio…" : "Invia ricevuta"}
                  </button>
                </div>
              </div>

              <div className="card" style={{ gridColumn: "span 8" }}>
                <div className="card-title">Pagamenti</div>
                <div className="muted" style={{ marginBottom: 10 }}>
                  I pagamenti sono append-only per motivi di audit.
                </div>
                <div className="row" style={{ justifyContent: "flex-start", alignItems: "stretch", flexWrap: "wrap" }}>
                  <input
                    className="auth-input"
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="Importo (EUR)"
                    value={paymentAmount}
                    onChange={(e) => setPaymentAmount(e.target.value)}
                    style={{ maxWidth: 160 }}
                  />
                  <select className="auth-input" value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value as any)} style={{ maxWidth: 180 }}>
                    <option value="bank_transfer">Bonifico</option>
                    <option value="cash">Contanti</option>
                    <option value="card">Carta</option>
                    <option value="other">Altro</option>
                  </select>
                  <input
                    className="auth-input"
                    placeholder="Transaction reference"
                    value={paymentTxRef}
                    onChange={(e) => setPaymentTxRef(e.target.value)}
                    style={{ minWidth: 220 }}
                  />
                  <input
                    className="auth-input"
                    type="datetime-local"
                    value={paymentReceivedAt}
                    onChange={(e) => setPaymentReceivedAt(e.target.value)}
                    style={{ minWidth: 220 }}
                  />
                  <input
                    className="auth-input"
                    placeholder="Note"
                    value={paymentRecordNote}
                    onChange={(e) => setPaymentRecordNote(e.target.value)}
                    style={{ minWidth: 260 }}
                  />
                  <button className="btn" type="button" disabled={savingPayment || !paymentAmount} onClick={() => addPayment(statementDetail.id)}>
                    {savingPayment ? "Adding…" : "Add payment"}
                  </button>
                </div>

                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Received</th>
                        <th>Amount (€)</th>
                        <th>Method</th>
                        <th>Reference</th>
                        <th>Note</th>
                        <th>Created by</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statementDetail.payments.map((p) => (
                        <tr key={p.id}>
                          <td>{formatDateTime(p.received_at)}</td>
                          <td>{formatCurrencyEur(p.amount_eur)}</td>
                          <td>{p.method}</td>
                          <td>{p.transaction_reference ?? "-"}</td>
                          <td>{p.note ?? "-"}</td>
                          <td>{p.created_by_username}</td>
                        </tr>
                      ))}
                      {!statementDetail.payments.length ? (
                        <tr>
                          <td colSpan={6} className="muted">No payments recorded yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card" style={{ gridColumn: "span 12" }}>
                <div className="card-title">Manual status override</div>
                <div className="muted" style={{ marginBottom: 10 }}>
                  Prefer using payments; overrides will reconcile totals automatically.
                </div>
                <div className="row" style={{ justifyContent: "flex-start", alignItems: "stretch" }}>
                  <textarea
                    className="auth-input"
                    value={paymentNote}
                    onChange={(e) => setPaymentNote(e.target.value)}
                    placeholder="Optional note for the audit trail"
                    style={{ minWidth: 260, minHeight: 72 }}
                  />
                  <button className="btn" type="button" onClick={() => updatePaymentStatus(statementDetail, "unpaid")}>
                    Mark unpaid
                  </button>
                  <button className="btn" type="button" onClick={() => updatePaymentStatus(statementDetail, "paid")}>
                    Mark paid
                  </button>
                  <button className="btn" type="button" onClick={() => waiveStatement(statementDetail.id)}>
                    Mark waived
                  </button>
                </div>
                {reminderPayload ? (
                  <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{reminderPayload}</pre>
                ) : null}
                {receiptPayload ? (
                  <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{receiptPayload}</pre>
                ) : null}
                {statementPayload ? (
                  <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{statementPayload}</pre>
                ) : null}
              </div>

              <div className="card" style={{ gridColumn: "span 7" }}>
                <div className="card-title">Included sessions</div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Station</th>
                        <th>RFID</th>
                        <th>Start</th>
                        <th>End</th>
                        <th>Energy (kWh)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statementDetail.sessions.map((session) => (
                        <tr key={session.id}>
                          <td>{session.station?.host ?? `#${session.station_id}`}</td>
                          <td>{session.rfid_user?.rfid_id ?? "-"}</td>
                          <td>{formatDateTime(session.start_time)}</td>
                          <td>{formatDateTime(session.end_time)}</td>
                          <td>{formatKwhFromWh(session.energy_wh)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card" style={{ gridColumn: "span 5" }}>
                <div className="card-title">Storico pagamenti</div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>By</th>
                        <th>Change</th>
                        <th>Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statementDetail.payment_history.map((event) => (
                        <tr key={event.id}>
                          <td>{formatDateTime(event.created_at)}</td>
                          <td>{event.changed_by_username}</td>
                          <td>{event.old_status} → {event.new_status}</td>
                          <td>{event.note ?? "-"}</td>
                        </tr>
                      ))}
                      {!statementDetail.payment_history.length ? (
                        <tr>
                          <td colSpan={4} className="muted">No payment events yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card" style={{ gridColumn: "span 12" }}>
                <div className="card-title">Notification history</div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Type</th>
                        <th>Recipient</th>
                        <th>Status</th>
                        <th>Subject</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statementDetail.notifications.map((notification) => (
                        <tr key={notification.id}>
                          <td>{formatDateTime(notification.created_at)}</td>
                          <td>{notification.notification_type}</td>
                          <td>{notification.recipient_email}</td>
                          <td>{notification.status}</td>
                          <td>{notification.subject}</td>
                          <td>
                            <button
                              className="btn"
                              type="button"
                              disabled={retryingNotificationId === notification.id || !["failed", "preview"].includes(notification.status)}
                              onClick={() => retryNotification(notification.id)}
                            >
                              {retryingNotificationId === notification.id ? "Retrying…" : "Retry"}
                            </button>
                          </td>
                        </tr>
                      ))}
                      {!statementDetail.notifications.length ? (
                        <tr>
                          <td colSpan={6} className="muted">No notifications created yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
              );
            })()
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

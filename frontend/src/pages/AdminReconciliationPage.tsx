import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type {
  AdminResidentRow,
  BillingPaymentImportJobDetailResponse,
  BillingPaymentImportJobSummaryResponse,
  BillingPeriodResponse,
  ReconciliationResponse,
  ReconciliationRow,
} from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import {
  DateRange,
  DateRangeControls,
  ErrorState,
  LoadingState,
  PageHead,
  formatCurrencyEur,
  formatDateTime,
  formatNumber,
  toApiRange,
} from "../shared/ui";

export default function AdminReconciliationPage() {
  const [periodId, setPeriodId] = useState("");
  const [residentId, setResidentId] = useState("");
  const [status, setStatus] = useState("");
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last30", fromDate: null, toDate: null }));
  const [selectedStatementId, setSelectedStatementId] = useState<number | null>(null);
  const [selectedImportJobId, setSelectedImportJobId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [downloadingErrors, setDownloadingErrors] = useState(false);

  const periodsFetcher = useMemo(() => () => endpoints.adminBillingPeriods(), []);
  const residentsFetcher = useMemo(() => () => endpoints.adminResidents(), []);
  const periodsQuery = useQuery<BillingPeriodResponse[]>(periodsFetcher);
  const residentsQuery = useQuery<AdminResidentRow[]>(residentsFetcher);

  const reconciliationFetcher = useMemo(
    () => () =>
      endpoints.adminReconciliation({
        period_id: periodId ? Number(periodId) : undefined,
        resident_id: residentId ? Number(residentId) : undefined,
        payment_status: status || undefined,
        received_from_date: toApiRange(range).from_date,
        received_to_date: toApiRange(range).to_date,
      }),
    [periodId, residentId, status, range],
  );
  const query = useQuery<ReconciliationResponse>(reconciliationFetcher);
  const importJobsFetcher = useMemo(() => () => endpoints.billingPaymentImportJobs(), []);
  const importJobsQuery = useQuery<BillingPaymentImportJobSummaryResponse[]>(importJobsFetcher);
  const importJobDetailFetcher = useMemo(
    () => () => (selectedImportJobId ? endpoints.billingPaymentImportJob(selectedImportJobId) : Promise.resolve(null)),
    [selectedImportJobId],
  );
  const importJobDetailQuery = useQuery<BillingPaymentImportJobDetailResponse | null>(importJobDetailFetcher);

  const rows = query.data?.rows ?? [];
  const selectedRow: ReconciliationRow | null = selectedStatementId ? rows.find((r) => r.statement_id === selectedStatementId) ?? null : null;

  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"bank_transfer" | "cash" | "card" | "other">("bank_transfer");
  const [paymentTxRef, setPaymentTxRef] = useState("");
  const [paymentReceivedAt, setPaymentReceivedAt] = useState("");
  const [paymentNote, setPaymentNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [reminderPayload, setReminderPayload] = useState<string | null>(null);

  async function importCsv(file: File) {
    setSaving(true);
    setActionError(null);
    setImportMessage(null);
    try {
      const result = await endpoints.importBillingPaymentsCsvUpload(file);
      setImportMessage(
        `Importati ${result.imported_count}, duplicati ${result.duplicate_count}, non abbinati ${result.unmatched_count}, falliti ${result.failed_count}`,
      );
      setSelectedImportJobId(result.import_job_id);
      importJobsQuery.refetch();
      importJobDetailQuery.refetch();
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Import CSV non riuscito");
    } finally {
      setSaving(false);
    }
  }

  async function downloadErrorsCsv(jobId: number) {
    setDownloadingErrors(true);
    setActionError(null);
    try {
      const res = await endpoints.exportImportJobErrorsCsv(jobId);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `import-job-${jobId}-errors.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Download CSV errori non riuscito");
    } finally {
      setDownloadingErrors(false);
    }
  }

  async function addPayment() {
    if (!selectedRow) return;
    setSaving(true);
    setActionError(null);
    try {
      const receivedAtIso = paymentReceivedAt ? new Date(paymentReceivedAt).toISOString() : new Date().toISOString();
      await endpoints.addBillingPayment(selectedRow.statement_id, {
        amount_eur: Number(paymentAmount),
        method: paymentMethod,
        transaction_reference: paymentTxRef.trim() || null,
        note: paymentNote.trim() || null,
        received_at: receivedAtIso,
      });
      setPaymentAmount("");
      setPaymentTxRef("");
      setPaymentReceivedAt("");
      setPaymentNote("");
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiungere il pagamento");
    } finally {
      setSaving(false);
    }
  }

  async function waive() {
    if (!selectedRow) return;
    setSaving(true);
    setActionError(null);
    try {
      await endpoints.waiveBillingStatement(selectedRow.statement_id, { note: paymentNote.trim() || undefined });
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile annullare il documento");
    } finally {
      setSaving(false);
    }
  }

  async function createReminder() {
    if (!selectedRow) return;
    setSaving(true);
    setActionError(null);
    setReminderPayload(null);
    try {
      const payload = await endpoints.createBillingReminder(selectedRow.statement_id);
      setReminderPayload(JSON.stringify(payload, null, 2));
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile creare i metadati notifica");
    } finally {
      setSaving(false);
    }
  }

  async function matchUnmatched(unmatchedPaymentId: number) {
    if (!selectedRow) return;
    setSaving(true);
    setActionError(null);
    try {
      await endpoints.matchUnmatchedPayment(unmatchedPaymentId, { statement_id: selectedRow.statement_id });
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile abbinare il pagamento");
    } finally {
      setSaving(false);
    }
  }

  async function ignoreUnmatched(unmatchedPaymentId: number) {
    setSaving(true);
    setActionError(null);
    try {
      await endpoints.ignoreUnmatchedPayment(unmatchedPaymentId, {});
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile ignorare il pagamento");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHead title="Verifiche" subtitle="Controllo importi, pagamenti registrati, annullamenti e notifiche" />

      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {(periodsQuery.loading || residentsQuery.loading) ? <LoadingState label="Caricamento filtri…" /> : null}
      {periodsQuery.error ? <ErrorState title="Impossibile caricare i periodi" message={periodsQuery.error} onRetry={periodsQuery.refetch} /> : null}
      {residentsQuery.error ? <ErrorState title="Impossibile caricare i residenti" message={residentsQuery.error} onRetry={residentsQuery.refetch} /> : null}

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row">
          <div className="pill">
            Periodo:&nbsp;
            <select value={periodId} onChange={(e) => setPeriodId(e.target.value)} style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}>
              <option value="">Tutti</option>
              {(periodsQuery.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="pill">
            Residente:&nbsp;
            <select value={residentId} onChange={(e) => setResidentId(e.target.value)} style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}>
              <option value="">Tutti</option>
              {(residentsQuery.data ?? []).filter((r) => r.role === "resident").map((r) => (
                <option key={r.app_user_id} value={r.app_user_id}>
                  {r.username}
                </option>
              ))}
            </select>
          </div>
          <div className="pill">
            Stato:&nbsp;
            <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}>
              <option value="">All</option>
              <option value="unpaid">Non pagato</option>
              <option value="partially_paid">Parzialmente pagato</option>
              <option value="paid">Pagato</option>
              <option value="waived">Annullato</option>
            </select>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <DateRangeControls range={range} onChange={setRange} />
        </div>
        <div style={{ marginTop: 10 }}>
          <input
            className="auth-input"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importCsv(file);
            }}
          />
          {importMessage ? <div className="muted" style={{ marginTop: 8 }}>{importMessage}</div> : null}
        </div>
      </div>

      {query.loading ? <LoadingState label="Caricamento verifiche…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare le verifiche" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale importi</div>
            <div className="metric">{formatCurrencyEur(query.data.total_amount_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale registrato</div>
            <div className="metric">{formatCurrencyEur(query.data.total_paid_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale residuo</div>
            <div className="metric">{formatCurrencyEur(query.data.total_due_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale ricevuto</div>
            <div className="metric">{formatCurrencyEur(query.data.total_received_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Non abbinati</div>
            <div className="metric">{query.data.unmatched_payments_count}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Importo non abbinato</div>
            <div className="metric">{formatCurrencyEur(query.data.unmatched_payments_amount_eur)}</div>
          </div>

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Importazioni</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Quando</th>
                    <th>File</th>
                    <th>Stato</th>
                    <th>Totale</th>
                    <th>Processate</th>
                    <th>Avanzamento</th>
                    <th>Abbinate</th>
                    <th>Non abbinate</th>
                    <th>Duplicate</th>
                    <th>Fallite</th>
                  </tr>
                </thead>
                <tbody>
                  {(importJobsQuery.data ?? []).map((job) => (
                    <tr
                      key={job.id}
                      onClick={() => setSelectedImportJobId(job.id)}
                      style={{ cursor: "pointer", opacity: selectedImportJobId === job.id ? 1 : 0.85 }}
                    >
                      <td>{formatDateTime(job.created_at)}</td>
                      <td>{job.filename}</td>
                      <td>{job.status}</td>
                      <td>{job.rows_total}</td>
                      <td>{job.rows_processed}</td>
                      <td>{job.progress_percent}%</td>
                      <td>{job.rows_matched}</td>
                      <td>{job.rows_unmatched}</td>
                      <td>{job.rows_duplicate}</td>
                      <td>{job.rows_failed}</td>
                    </tr>
                  ))}
                  {!(importJobsQuery.data ?? []).length ? (
                    <tr>
                      <td colSpan={10} className="muted">Nessuna importazione.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          {importJobDetailQuery.data ? (
            <div className="card" style={{ gridColumn: "span 12" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <div className="card-title">Import rows for job #{importJobDetailQuery.data.id}</div>
                <button
                  className="btn"
                  type="button"
                  disabled={downloadingErrors}
                  onClick={() => downloadErrorsCsv(importJobDetailQuery.data!.id)}
                >
                  {downloadingErrors ? "Downloading…" : "Download errors CSV"}
                </button>
              </div>
              <div className="muted" style={{ marginBottom: 10 }}>
                {importJobDetailQuery.data.filename} • {importJobDetailQuery.data.status}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Riga</th>
                      <th>Riferimento</th>
                      <th>Documento</th>
                      <th>Importo</th>
                      <th>Ricevuto</th>
                      <th>Rif. transazione</th>
                      <th>Stato</th>
                      <th>Errore</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importJobDetailQuery.data.rows.map((row) => (
                      <tr key={row.id}>
                        <td>{row.row_number}</td>
                        <td>{row.raw_payment_reference ?? "-"}</td>
                        <td>{row.raw_statement_number ?? "-"}</td>
                        <td>{row.amount_eur == null ? "-" : formatCurrencyEur(row.amount_eur)}</td>
                        <td>{formatDateTime(row.received_at)}</td>
                        <td>{row.transaction_reference ?? "-"}</td>
                        <td>{row.status}</td>
                        <td>{row.error_message ?? "-"}</td>
                      </tr>
                    ))}
                    {!importJobDetailQuery.data.rows.length ? (
                      <tr>
                        <td colSpan={8} className="muted">Nessun risultato per questa importazione.</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Documenti</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Documento</th>
                    <th>Residente</th>
                    <th>Totale</th>
                    <th>Registrato</th>
                    <th>Residuo</th>
                    <th>Stato</th>
                    <th>Ultimo pagamento</th>
                    <th>Notifiche</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.statement_id}
                      onClick={() => setSelectedStatementId(row.statement_id)}
                      style={{ cursor: "pointer", opacity: selectedStatementId === row.statement_id ? 1 : 0.85 }}
                    >
                      <td style={{ fontWeight: 700 }}>{row.statement_number}</td>
                      <td>{row.resident_username}</td>
                      <td>{formatCurrencyEur(row.amount_eur)}</td>
                      <td>{formatCurrencyEur(row.amount_paid_eur)}</td>
                      <td>{formatCurrencyEur(row.amount_due_eur)}</td>
                      <td>{row.payment_status}</td>
                      <td>{formatDateTime(row.last_payment_at)}</td>
                      <td>{row.reminder_count}</td>
                    </tr>
                  ))}
                  {!rows.length ? (
                    <tr>
                      <td colSpan={8} className="muted">Nessun documento corrisponde ai filtri selezionati.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          {selectedRow ? (
            <div className="card" style={{ gridColumn: "span 12" }}>
              <div className="card-title">Azioni per {selectedRow.statement_number}</div>
              <div className="muted" style={{ marginBottom: 10 }}>
                Riferimento: <strong>{selectedRow.payment_reference}</strong>
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
                <input className="auth-input" placeholder="Riferimento transazione" value={paymentTxRef} onChange={(e) => setPaymentTxRef(e.target.value)} style={{ minWidth: 220 }} />
                <input className="auth-input" type="datetime-local" value={paymentReceivedAt} onChange={(e) => setPaymentReceivedAt(e.target.value)} style={{ minWidth: 220 }} />
                <input className="auth-input" placeholder="Nota" value={paymentNote} onChange={(e) => setPaymentNote(e.target.value)} style={{ minWidth: 260 }} />
                <button className="btn" type="button" disabled={saving || !paymentAmount} onClick={addPayment}>
                  {saving ? "Salvataggio…" : "Aggiungi pagamento"}
                </button>
                <button className="btn" type="button" disabled={saving} onClick={waive}>
                  Annulla
                </button>
                <button className="btn" type="button" disabled={saving} onClick={createReminder}>
                  Crea metadati notifica
                </button>
              </div>
              {reminderPayload ? <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{reminderPayload}</pre> : null}
            </div>
          ) : null}

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Pagamenti non abbinati</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Riferimento</th>
                    <th>Importo</th>
                    <th>Ricevuto</th>
                    <th>Rif. transazione</th>
                    <th>Stato</th>
                    <th>Azione</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.unmatched_payments.map((row) => (
                    <tr key={row.id}>
                      <td>{row.raw_reference ?? "-"}</td>
                      <td>{formatCurrencyEur(row.amount_eur)}</td>
                      <td>{formatDateTime(row.received_at)}</td>
                      <td>{row.transaction_reference ?? "-"}</td>
                      <td>{row.status}</td>
                      <td>
                        <div className="row" style={{ justifyContent: "flex-start" }}>
                          <button className="btn" type="button" disabled={saving || !selectedRow || row.status !== "unmatched"} onClick={() => matchUnmatched(row.id)}>
                            Abbina al selezionato
                          </button>
                          <button className="btn" type="button" disabled={saving || row.status !== "unmatched"} onClick={() => ignoreUnmatched(row.id)}>
                            Ignora
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!query.data.unmatched_payments.length ? (
                    <tr>
                      <td colSpan={6} className="muted">Nessun pagamento non abbinato per i filtri selezionati.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { BillingReminderRuleResponse, BillingStatementResponse, ReminderRunResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatCurrencyEur, formatDateTime } from "../shared/ui";

export default function AdminRemindersPage() {
  const ruleFetcher = useMemo(() => () => endpoints.billingReminderRule(), []);
  const ruleQuery = useQuery<BillingReminderRuleResponse>(ruleFetcher);
  const candidatesFetcher = useMemo(() => () => endpoints.reminderCandidates(), []);
  const candidatesQuery = useQuery<BillingStatementResponse[]>(candidatesFetcher);

  const [enabled, setEnabled] = useState(false);
  const [daysAfterClose, setDaysAfterClose] = useState(0);
  const [repeatEveryDays, setRepeatEveryDays] = useState(14);
  const [maxReminders, setMaxReminders] = useState(3);
  const [minAmountDue, setMinAmountDue] = useState("0.00");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<ReminderRunResponse | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!ruleQuery.data) return;
    setEnabled(ruleQuery.data.enabled);
    setDaysAfterClose(ruleQuery.data.days_after_period_close);
    setRepeatEveryDays(ruleQuery.data.repeat_every_days);
    setMaxReminders(ruleQuery.data.max_reminders);
    setMinAmountDue(ruleQuery.data.min_amount_due_eur.toFixed(2));
  }, [ruleQuery.data]);

  async function saveRule(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setActionError(null);
    setMessage(null);
    try {
      await endpoints.updateBillingReminderRule({
        enabled,
        days_after_period_close: daysAfterClose,
        repeat_every_days: repeatEveryDays,
        max_reminders: maxReminders,
        min_amount_due_eur: Number(minAmountDue || "0"),
      });
      setMessage("Impostazioni salvate.");
      ruleQuery.refetch();
      candidatesQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile salvare le impostazioni");
    } finally {
      setSaving(false);
    }
  }

  async function runBatch() {
    setRunning(true);
    setActionError(null);
    setRunResult(null);
    try {
      const result = await endpoints.runReminders();
      setRunResult(result);
      candidatesQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Esecuzione notifiche non riuscita");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <PageHead title="Notifiche" subtitle="Configurazione e strumenti operativi (facoltativi)" />

      {ruleQuery.loading ? <LoadingState label="Caricamento impostazioni…" /> : null}
      {ruleQuery.error ? <ErrorState title="Impossibile caricare le impostazioni" message={ruleQuery.error} onRetry={ruleQuery.refetch} /> : null}
      {candidatesQuery.error ? <ErrorState title="Impossibile caricare i candidati" message={candidatesQuery.error} onRetry={candidatesQuery.refetch} /> : null}
      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}

      <div className="grid">
        <div className="card" style={{ gridColumn: "span 6" }}>
          <div className="card-title">Regola</div>
          <form className="auth-form" onSubmit={saveRule}>
            <label className="auth-label">
              Attiva
              <select className="auth-input" value={enabled ? "yes" : "no"} onChange={(e) => setEnabled(e.target.value === "yes")}>
                <option value="no">No</option>
                <option value="yes">Sì</option>
              </select>
            </label>
            <label className="auth-label">
              Giorni dopo chiusura periodo
              <input className="auth-input" type="number" min={0} value={daysAfterClose} onChange={(e) => setDaysAfterClose(Number(e.target.value))} />
            </label>
            <label className="auth-label">
              Ripeti ogni (giorni)
              <input className="auth-input" type="number" min={1} value={repeatEveryDays} onChange={(e) => setRepeatEveryDays(Number(e.target.value))} />
            </label>
            <label className="auth-label">
              Numero massimo notifiche
              <input className="auth-input" type="number" min={0} value={maxReminders} onChange={(e) => setMaxReminders(Number(e.target.value))} />
            </label>
            <label className="auth-label">
              Importo minimo residuo (EUR)
              <input className="auth-input" type="number" min={0} step="0.01" value={minAmountDue} onChange={(e) => setMinAmountDue(e.target.value)} />
            </label>
            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Salvataggio…" : "Salva"}
            </button>
            {message ? <div className="muted">{message}</div> : null}
          </form>
        </div>

        <div className="card" style={{ gridColumn: "span 6" }}>
          <div className="card-title">Esecuzione</div>
          <div className="muted" style={{ marginBottom: 10 }}>
            Candidati: {(candidatesQuery.data ?? []).length}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn" type="button" disabled={running} onClick={() => candidatesQuery.refetch()}>
              Aggiorna candidati
            </button>
            <button className="btn" type="button" disabled={running} onClick={runBatch}>
              {running ? "Esecuzione…" : "Esegui notifiche"}
            </button>
          </div>
          {runResult ? <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(runResult, null, 2)}</pre> : null}
        </div>

        <div className="card" style={{ gridColumn: "span 12" }}>
          <div className="card-title">Anteprima candidati</div>
          {candidatesQuery.loading ? <LoadingState label="Caricamento candidati…" /> : null}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Documento</th>
                  <th>Residente</th>
                  <th>Periodo</th>
                  <th>Residuo</th>
                  <th>Notifiche</th>
                  <th>Ultima notifica</th>
                </tr>
              </thead>
              <tbody>
                {(candidatesQuery.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>{row.statement_number}</td>
                    <td>{row.resident_username}</td>
                    <td>{row.period_name}</td>
                    <td>{formatCurrencyEur(row.amount_due_eur)}</td>
                    <td>{row.reminder_count}</td>
                    <td>{formatDateTime(row.last_reminder_at)}</td>
                  </tr>
                ))}
                {!(candidatesQuery.data ?? []).length ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      Nessun candidato al momento.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

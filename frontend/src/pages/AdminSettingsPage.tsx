import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { AdminSettingsResponse, EmailHealthResponse, TestEmailResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

export default function AdminSettingsPage() {
  const fetcher = useMemo(() => () => endpoints.adminSettings(), []);
  const settingsQuery = useQuery<AdminSettingsResponse>(fetcher);
  const emailHealthFetcher = useMemo(() => () => endpoints.adminEmailHealth(), []);
  const emailHealthQuery = useQuery<EmailHealthResponse>(emailHealthFetcher);
  const [price, setPrice] = useState("0.30");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testRecipient, setTestRecipient] = useState("");
  const [sendingTest, setSendingTest] = useState(false);
  const [testResult, setTestResult] = useState<TestEmailResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsQuery.data) return;
    setPrice(settingsQuery.data.energy_price_eur_per_kwh.toString());
  }, [settingsQuery.data]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const updated = await endpoints.updateAdminSettings({ energy_price_eur_per_kwh: Number(price) });
      setPrice(updated.energy_price_eur_per_kwh.toString());
      setMessage("Prezzo energia aggiornato.");
      settingsQuery.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare le impostazioni");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestSend(e: FormEvent) {
    e.preventDefault();
    setSendingTest(true);
    setTestError(null);
    setTestResult(null);
    try {
      const payload = await endpoints.testAdminEmail({ recipient_email: testRecipient.trim() });
      setTestResult(payload);
      emailHealthQuery.refetch();
    } catch (err) {
      setTestError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Invio email di test non riuscito");
    } finally {
      setSendingTest(false);
    }
  }

  return (
    <div>
      <PageHead title="Impostazioni" subtitle="Prezzo energia condominiale usato per stimare i costi di ricarica" />

      {settingsQuery.loading ? <LoadingState label="Caricamento impostazioni…" /> : null}
      {settingsQuery.error ? (
        <ErrorState title="Impossibile caricare le impostazioni" message={settingsQuery.error} onRetry={settingsQuery.refetch} />
      ) : null}
      {error ? <ErrorState title="Aggiornamento non riuscito" message={error} /> : null}
      {testError ? <ErrorState title="Test email non riuscito" message={testError} /> : null}

      <div className="grid">
        <div className="card" style={{ maxWidth: 480, gridColumn: "span 6" }}>
          <div className="card-title">Prezzo energia</div>
          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-label">
              Prezzo energia (EUR per kWh)
              <input className="auth-input" type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} required />
            </label>
            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Salvataggio…" : "Salva"}
            </button>
            {message ? <div className="muted">{message}</div> : null}
          </form>
        </div>

        <div className="card" style={{ gridColumn: "span 6" }}>
          <div className="card-title">Email</div>
          {emailHealthQuery.loading ? <LoadingState label="Verifica invio email…" /> : null}
          {emailHealthQuery.error ? (
            <ErrorState title="Impossibile caricare lo stato email" message={emailHealthQuery.error} onRetry={emailHealthQuery.refetch} />
          ) : null}
          {emailHealthQuery.data ? (
            <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
              <div><strong>Stato:</strong> {emailHealthQuery.data.status}</div>
              <div className="muted">Host: {emailHealthQuery.data.host ?? "-"}</div>
              <div className="muted">Porta: {emailHealthQuery.data.port ?? "-"}</div>
              <div className="muted">
                TLS: {emailHealthQuery.data.use_tls == null ? "-" : emailHealthQuery.data.use_tls ? "Attivo" : "Disattivo"}
              </div>
              <div className="muted">Messaggio: {emailHealthQuery.data.message ?? "-"}</div>
            </div>
          ) : null}

          <form className="auth-form" onSubmit={handleTestSend}>
            <label className="auth-label">
              Destinatario test
              <input className="auth-input" type="email" value={testRecipient} onChange={(e) => setTestRecipient(e.target.value)} placeholder="recipient@example.com" required />
            </label>
            <button className="btn" type="submit" disabled={sendingTest || !testRecipient.trim()}>
              {sendingTest ? "Invio…" : "Invia email di test"}
            </button>
          </form>
          {testResult ? (
            <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(testResult, null, 2)}</pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}

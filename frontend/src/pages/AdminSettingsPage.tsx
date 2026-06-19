import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type {
  AdminSettingsResponse,
  AdminTelegramStatusResponse,
  AdminTelegramTestSendResponse,
  EmailHealthResponse,
  TestEmailResponse,
} from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

export default function AdminSettingsPage() {
  const fetcher = useMemo(() => () => endpoints.adminSettings(), []);
  const settingsQuery = useQuery<AdminSettingsResponse>(fetcher);
  const emailHealthFetcher = useMemo(() => () => endpoints.adminEmailHealth(), []);
  const emailHealthQuery = useQuery<EmailHealthResponse>(emailHealthFetcher);
  const telegramStatusFetcher = useMemo(() => () => endpoints.adminTelegramStatus(), []);
  const telegramStatusQuery = useQuery<AdminTelegramStatusResponse>(telegramStatusFetcher);
  const [price, setPrice] = useState("0.30");
  const [telegramSettings, setTelegramSettings] = useState({
    telegram_station_available_enabled: true,
    telegram_charging_completed_enabled: true,
    telegram_agent_offline_enabled: true,
    telegram_agent_recovered_enabled: true,
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testRecipient, setTestRecipient] = useState("");
  const [sendingTest, setSendingTest] = useState(false);
  const [testResult, setTestResult] = useState<TestEmailResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [telegramChatId, setTelegramChatId] = useState("");
  const [sendingTelegramTest, setSendingTelegramTest] = useState(false);
  const [telegramTestResult, setTelegramTestResult] = useState<AdminTelegramTestSendResponse | null>(null);
  const [telegramTestError, setTelegramTestError] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsQuery.data) return;
    setPrice(settingsQuery.data.energy_price_eur_per_kwh.toString());
    setTelegramSettings({
      telegram_station_available_enabled: settingsQuery.data.telegram_station_available_enabled,
      telegram_charging_completed_enabled: settingsQuery.data.telegram_charging_completed_enabled,
      telegram_agent_offline_enabled: settingsQuery.data.telegram_agent_offline_enabled,
      telegram_agent_recovered_enabled: settingsQuery.data.telegram_agent_recovered_enabled,
    });
  }, [settingsQuery.data]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const updated = await endpoints.updateAdminSettings({
        energy_price_eur_per_kwh: Number(price),
        ...telegramSettings,
      });
      setPrice(updated.energy_price_eur_per_kwh.toString());
      setTelegramSettings({
        telegram_station_available_enabled: updated.telegram_station_available_enabled,
        telegram_charging_completed_enabled: updated.telegram_charging_completed_enabled,
        telegram_agent_offline_enabled: updated.telegram_agent_offline_enabled,
        telegram_agent_recovered_enabled: updated.telegram_agent_recovered_enabled,
      });
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

  async function handleTelegramTestSend(e: FormEvent) {
    e.preventDefault();
    setSendingTelegramTest(true);
    setTelegramTestError(null);
    setTelegramTestResult(null);
    try {
      const payload = await endpoints.testAdminTelegram({ chat_id: telegramChatId.trim() });
      setTelegramTestResult(payload);
      telegramStatusQuery.refetch();
    } catch (err) {
      setTelegramTestError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Invio Telegram di test non riuscito");
    } finally {
      setSendingTelegramTest(false);
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
      {telegramTestError ? <ErrorState title="Test Telegram non riuscito" message={telegramTestError} /> : null}

      <div className="grid">
        <div className="card" style={{ maxWidth: 480, gridColumn: "span 6" }}>
          <div className="card-title">Prezzo energia</div>
          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-label">
              Prezzo energia (EUR per kWh)
              <input className="auth-input" type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} required />
            </label>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={telegramSettings.telegram_station_available_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_station_available_enabled: e.target.checked }))}
              />
              <span>Telegram: colonnina disponibile</span>
            </label>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={telegramSettings.telegram_charging_completed_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_charging_completed_enabled: e.target.checked }))}
              />
              <span>Telegram: ricarica completata</span>
            </label>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={telegramSettings.telegram_agent_offline_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_agent_offline_enabled: e.target.checked }))}
              />
              <span>Telegram: agente offline</span>
            </label>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={telegramSettings.telegram_agent_recovered_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_agent_recovered_enabled: e.target.checked }))}
              />
              <span>Telegram: agente ripristinato</span>
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

        <div className="card" style={{ gridColumn: "span 12" }}>
          <div className="card-title">Telegram</div>
          {telegramStatusQuery.loading ? <LoadingState label="Verifica bot Telegram…" /> : null}
          {telegramStatusQuery.error ? (
            <ErrorState title="Impossibile caricare lo stato Telegram" message={telegramStatusQuery.error} onRetry={telegramStatusQuery.refetch} />
          ) : null}
          {telegramStatusQuery.data ? (
            <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
              <div><strong>Stato:</strong> {telegramStatusQuery.data.status}</div>
              <div className="muted">Configurato: {telegramStatusQuery.data.configured ? "Si" : "No"}</div>
              <div className="muted">Bot: {telegramStatusQuery.data.bot_username ?? "-"}</div>
              <div className="muted">Webhook: {telegramStatusQuery.data.webhook_path}</div>
              <div className="muted">Messaggio: {telegramStatusQuery.data.message ?? "-"}</div>
            </div>
          ) : null}

          <form className="auth-form" onSubmit={handleTelegramTestSend}>
            <label className="auth-label">
              Chat ID test
              <input className="auth-input" value={telegramChatId} onChange={(e) => setTelegramChatId(e.target.value)} placeholder="123456789" required />
            </label>
            <button className="btn" type="submit" disabled={sendingTelegramTest || !telegramChatId.trim()}>
              {sendingTelegramTest ? "Invio…" : "Invia Telegram di test"}
            </button>
          </form>
          {telegramTestResult ? (
            <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(telegramTestResult, null, 2)}</pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}

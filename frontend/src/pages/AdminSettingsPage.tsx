import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type {
  AdminResidentRow,
  AdminQueueSettingsResponse,
  AdminSettingsResponse,
  AdminTelegramSimulationResponse,
  AdminTelegramStatusResponse,
  AdminTelegramTestSendResponse,
  EmailHealthResponse,
  PushTestResponse,
  TestEmailResponse,
} from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import * as pushService from "../shared/notifications/pushService";
import { AdminQueueSettingsCard } from "../shared/ui/AdminQueueSettingsCard";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

type AdminSettingsTelegramResponse = AdminSettingsResponse & {
  telegram_station_busy_enabled: boolean;
  telegram_station_back_online_enabled: boolean;
};

type TelegramSimulationEndpoints = typeof endpoints & {
  simulateAdminTelegram: (params: {
    resident_app_user_id: number;
    notification_type: string;
  }) => Promise<AdminTelegramSimulationResponse>;
};

export default function AdminSettingsPage() {
  const telegramEndpoints = endpoints as TelegramSimulationEndpoints;
  const fetcher = useMemo(
    () => async () => (await endpoints.adminSettings()) as AdminSettingsTelegramResponse,
    [],
  );
  const settingsQuery = useQuery<AdminSettingsTelegramResponse>(fetcher);
  const emailHealthFetcher = useMemo(() => () => endpoints.adminEmailHealth(), []);
  const emailHealthQuery = useQuery<EmailHealthResponse>(emailHealthFetcher);
  const queueSettingsFetcher = useMemo(() => () => endpoints.adminQueueSettings(), []);
  const queueSettingsQuery = useQuery<AdminQueueSettingsResponse>(queueSettingsFetcher);
  const telegramStatusFetcher = useMemo(() => () => endpoints.adminTelegramStatus(), []);
  const telegramStatusQuery = useQuery<AdminTelegramStatusResponse>(telegramStatusFetcher);
  const residentsFetcher = useMemo(() => () => endpoints.adminResidents(), []);
  const residentsQuery = useQuery<AdminResidentRow[]>(residentsFetcher);
  const [price, setPrice] = useState("0.30");
  const [telegramSettings, setTelegramSettings] = useState({
    telegram_station_available_enabled: true,
    telegram_station_busy_enabled: false,
    telegram_station_back_online_enabled: false,
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
  const [pushState, setPushState] = useState<pushService.BrowserPushState>("disabled");
  const [pushLoading, setPushLoading] = useState(false);
  const [pushTestResult, setPushTestResult] = useState<PushTestResponse | null>(null);
  const [pushError, setPushError] = useState<string | null>(null);
  const [simResidentId, setSimResidentId] = useState("");
  const [simulatingType, setSimulatingType] = useState<string | null>(null);
  const [simulationResult, setSimulationResult] = useState<AdminTelegramSimulationResponse | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsQuery.data) return;
    setPrice(settingsQuery.data.energy_price_eur_per_kwh.toString());
    setTelegramSettings({
      telegram_station_available_enabled: settingsQuery.data.telegram_station_available_enabled,
      telegram_station_busy_enabled: settingsQuery.data.telegram_station_busy_enabled,
      telegram_station_back_online_enabled: settingsQuery.data.telegram_station_back_online_enabled,
      telegram_charging_completed_enabled: settingsQuery.data.telegram_charging_completed_enabled,
      telegram_agent_offline_enabled: settingsQuery.data.telegram_agent_offline_enabled,
      telegram_agent_recovered_enabled: settingsQuery.data.telegram_agent_recovered_enabled,
    });
  }, [settingsQuery.data]);

  useEffect(() => {
    void refreshPushState();
  }, []);

  async function refreshPushState() {
    try {
      setPushState(await pushService.resolveBrowserPushState(false));
    } catch {
      setPushState("disabled");
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const updated = (await endpoints.updateAdminSettings({
        energy_price_eur_per_kwh: Number(price),
        ...telegramSettings,
      } as any)) as AdminSettingsTelegramResponse;
      setPrice(updated.energy_price_eur_per_kwh.toString());
      setTelegramSettings({
        telegram_station_available_enabled: updated.telegram_station_available_enabled,
        telegram_station_busy_enabled: updated.telegram_station_busy_enabled,
        telegram_station_back_online_enabled: updated.telegram_station_back_online_enabled,
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

  async function runSimulation(notificationType: string) {
    const residentId = Number(simResidentId);
    if (!Number.isFinite(residentId) || residentId <= 0) return;
    setSimulatingType(notificationType);
    setSimulationError(null);
    setSimulationResult(null);
    try {
      const payload = await telegramEndpoints.simulateAdminTelegram({
        resident_app_user_id: residentId,
        notification_type: notificationType,
      });
      setSimulationResult(payload);
    } catch (err) {
      setSimulationError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Simulazione Telegram non riuscita");
    } finally {
      setSimulatingType(null);
    }
  }

  async function enableBrowserPush() {
    setPushLoading(true);
    setPushError(null);
    setPushTestResult(null);
    try {
      const permission = await pushService.requestNotificationPermission();
      if (permission !== "granted") {
        setPushError("Permesso notifiche non concesso.");
        await refreshPushState();
        return;
      }
      await pushService.subscribeToPush();
      await refreshPushState();
    } catch (err) {
      setPushError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile attivare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  async function sendPushTest() {
    setPushLoading(true);
    setPushError(null);
    setPushTestResult(null);
    try {
      const payload = await endpoints.pushTest();
      setPushTestResult(payload);
      await refreshPushState();
    } catch (err) {
      setPushError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Invio push di test non riuscito");
    } finally {
      setPushLoading(false);
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
      {pushError ? <ErrorState title="Test push non riuscito" message={pushError} /> : null}
      {simulationError ? <ErrorState title="Simulazione Telegram non riuscita" message={simulationError} /> : null}
      {queueSettingsQuery.error ? (
        <ErrorState title="Impossibile caricare le impostazioni coda" message={queueSettingsQuery.error} onRetry={queueSettingsQuery.refetch} />
      ) : null}

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
                checked={telegramSettings.telegram_station_busy_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_station_busy_enabled: e.target.checked }))}
              />
              <span>Telegram: colonnina occupata</span>
            </label>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={telegramSettings.telegram_station_back_online_enabled}
                onChange={(e) => setTelegramSettings((v) => ({ ...v, telegram_station_back_online_enabled: e.target.checked }))}
              />
              <span>Telegram: colonnina tornata online</span>
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
        <AdminQueueSettingsCard />

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

        <div className="card" style={{ gridColumn: "span 12" }}>
          <div className="card-title">Push Browser</div>
          <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
            <div><strong>Stato:</strong> {pushState === "active" ? "Attive" : pushState === "unsupported" ? "Non supportate" : "Disattivate"}</div>
            <div className="muted">Attiva il browser corrente e invia una notifica reale di test all'account admin connesso.</div>
          </div>
          <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
            <button className="btn" type="button" onClick={enableBrowserPush} disabled={pushLoading || pushState === "unsupported"}>
              {pushLoading ? "Attivazione..." : "Attiva notifiche browser"}
            </button>
            <button className="btn" type="button" onClick={sendPushTest} disabled={pushLoading || pushState !== "active"}>
              {pushLoading ? "Invio..." : "Invia notifica di test"}
            </button>
          </div>
          {pushTestResult ? (
            <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(pushTestResult, null, 2)}</pre>
          ) : null}
        </div>

        <div className="card" style={{ gridColumn: "span 12" }}>
          <div className="card-title">Telegram Testing</div>
          {residentsQuery.loading ? <LoadingState label="Caricamento residenti…" /> : null}
          {residentsQuery.error ? (
            <ErrorState title="Impossibile caricare i residenti" message={residentsQuery.error} onRetry={residentsQuery.refetch} />
          ) : null}
          <div className="auth-form">
            <label className="auth-label">
              Residente
              <select className="auth-input" value={simResidentId} onChange={(e) => setSimResidentId(e.target.value)}>
                <option value="">Seleziona residente</option>
                {(residentsQuery.data ?? []).map((resident) => (
                  <option key={resident.app_user_id} value={resident.app_user_id}>
                    {resident.username} (#{resident.app_user_id})
                  </option>
                ))}
              </select>
            </label>
            <div className="muted">Non modifica sessioni o stato delle colonnine: invia solo notifiche Telegram reali e crea il relativo audit.</div>
            <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
              {[
                ["station_available", "Test Colonnina Disponibile"],
                ["station_busy", "Test Colonnina Occupata"],
                ["charging_completed", "Test Ricarica Completata"],
                ["station_back_online", "Test Colonnina Tornata Online"],
                ["agent_offline", "Test Agent Offline"],
                ["agent_recovered", "Test Agent Ripristinato"],
              ].map(([notificationType, label]) => (
                <button
                  key={notificationType}
                  className="btn btn-secondary"
                  type="button"
                  disabled={!simResidentId || simulatingType !== null}
                  onClick={() => runSimulation(notificationType)}
                >
                  {simulatingType === notificationType ? "Invio…" : label}
                </button>
              ))}
            </div>
          </div>
          {simulationResult ? (
            <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(simulationResult, null, 2)}</pre>
          ) : null}
        </div>
      </div>
    </div>
  );
}

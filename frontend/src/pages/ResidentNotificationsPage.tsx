import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentNotificationPreferences, ResidentNotificationPreferencesUpdate, ResidentProfileResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, StatusBadge, Surface } from "../shared/ui";
import * as pushService from "../shared/notifications/pushService";

export default function ResidentNotificationsPage() {
  const fetcher = useMemo(() => () => endpoints.residentNotificationPreferences(), []);
  const query = useQuery<ResidentNotificationPreferences>(fetcher);
  const profileFetcher = useMemo(() => () => endpoints.residentProfile(), []);
  const profileQuery = useQuery<ResidentProfileResponse>(profileFetcher);

  const [values, setValues] = useState<ResidentNotificationPreferencesUpdate>({
    charging_completed: true,
    station_available: true,
    station_busy: true,
    station_back_online: true,
    agent_offline: true,
    agent_recovered: true,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [pushLoading, setPushLoading] = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  const [pushMessage, setPushMessage] = useState<string | null>(null);
  const [pushState, setPushState] = useState<pushService.BrowserPushState>("disabled");
  const [pushDiag, setPushDiag] = useState<pushService.PushDiagnosticsSnapshot | null>(null);
  const [pushDiagLoading, setPushDiagLoading] = useState(false);
  const [pushTestDetails, setPushTestDetails] = useState<{
    delivery_status: string;
    delivered_count: number;
    timestamp: string;
  } | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setValues({
      charging_completed: query.data.charging_completed,
      station_available: query.data.station_available,
      station_busy: query.data.station_busy,
      station_back_online: query.data.station_back_online,
      agent_offline: query.data.agent_offline,
      agent_recovered: query.data.agent_recovered,
    });
  }, [query.data]);

  useEffect(() => {
    if (!profileQuery.data) return;
    void refreshPushState(profileQuery.data.push.subscribed);
  }, [profileQuery.data]);

  useEffect(() => {
    void refreshPushDiagnostics();
  }, []);

  async function refreshPushDiagnostics() {
    setPushDiagLoading(true);
    try {
      setPushDiag(await pushService.collectPushDiagnosticsSnapshot());
    } finally {
      setPushDiagLoading(false);
    }
  }

  async function refreshPushState(serverSubscribed: boolean) {
    try {
      if (pushService.getNotificationPermissionState() === "granted") {
        await pushService.syncExistingSubscription().catch(() => undefined);
      }
      setPushState(await pushService.resolveBrowserPushState(serverSubscribed));
    } catch {
      setPushState(serverSubscribed ? "active" : "disabled");
    }
  }

  function pushStatusMeta() {
    if (pushState === "unsupported") {
      return { label: "Non supportate", tone: "warn" as const };
    }
    if (pushState === "active") {
      return { label: "Attive", tone: "ok" as const };
    }
    return { label: "Disattivate", tone: "neutral" as const };
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      await endpoints.updateResidentNotificationPreferences(values);
      setSaveMessage("Impostazioni salvate.");
      query.refetch();
    } catch (err) {
      setSaveError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Salvataggio non riuscito");
    } finally {
      setSaving(false);
    }
  }

  async function enablePushNotifications() {
    setPushError(null);
    setPushMessage(null);
    setPushLoading(true);
    try {
      await refreshPushDiagnostics();
      const permission = await pushService.requestNotificationPermission();
      await refreshPushDiagnostics();
      if (permission !== "granted") {
        setPushError("Permesso notifiche non concesso.");
        await refreshPushState(false);
        return;
      }
      await pushService.subscribeToPush();
      await refreshPushDiagnostics();
      setPushMessage("Notifiche push attivate.");
      await profileQuery.refetch();
      await refreshPushState(true);
    } catch (err) {
      setPushError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile attivare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  async function disablePushNotifications() {
    setPushError(null);
    setPushMessage(null);
    setPushLoading(true);
    setPushTestDetails(null);
    try {
      await pushService.unsubscribeFromPush();
      await refreshPushDiagnostics();
      setPushMessage("Notifiche push disattivate.");
      await profileQuery.refetch();
      await refreshPushState(false);
    } catch (err) {
      setPushError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile disattivare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  async function sendPushSelfTest() {
    setPushError(null);
    setPushMessage(null);
    setPushLoading(true);
    try {
      const payload = await pushService.sendPushTest();
      const details = {
        delivery_status: payload.delivery_status,
        delivered_count: payload.delivered_count,
        timestamp: new Date().toISOString(),
      };
      setPushTestDetails(details);
      if (details.delivered_count <= 0) {
        setPushMessage("Nessun dispositivo registrato per le notifiche push.");
        return;
      }
      setPushMessage("Notifica di test inviata correttamente.");
    } catch {
      setPushTestDetails(null);
      setPushError("Invio notifica non riuscito. Riprova più tardi.");
    } finally {
      setPushLoading(false);
    }
  }

  return (
    <div>
      <PageHead title="Notifiche" subtitle="Scegli quali aggiornamenti ricevere" />

      {query.loading ? <LoadingState label="Caricamento preferenze…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare le preferenze" message={query.error} onRetry={query.refetch} /> : null}
      {saveError ? <ErrorState title="Salvataggio non riuscito" message={saveError} /> : null}
      {pushError ? <ErrorState title="Notifiche push" message={pushError} /> : null}
      {pushMessage ? <div className="muted">{pushMessage}</div> : null}

      <div className="grid">
        <div style={{ gridColumn: "span 12" }}>
          <Surface title="Preferenze" subtitle="Notifiche utili per l'uso quotidiano">
            <form className="auth-form" onSubmit={onSave}>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={values.charging_completed}
                  onChange={(e) => setValues((v) => ({ ...v, charging_completed: e.target.checked }))}
                />
                <span>Ricarica completata</span>
              </label>

              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={values.station_available}
                  onChange={(e) => setValues((v) => ({ ...v, station_available: e.target.checked }))}
                />
                <span>Colonnina disponibile</span>
              </label>

              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={values.station_busy}
                  onChange={(e) => setValues((v) => ({ ...v, station_busy: e.target.checked }))}
                />
                <span>Colonnina occupata</span>
              </label>

              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={values.station_back_online}
                  onChange={(e) => setValues((v) => ({ ...v, station_back_online: e.target.checked }))}
                />
                <span>Colonnina di nuovo disponibile</span>
              </label>

              <button className="btn btn--primary touch-safe" type="submit" disabled={saving}>
                {saving ? "Salvataggio…" : "Salva"}
              </button>
              {saveMessage ? <StatusBadge tone="ok" label={saveMessage} /> : null}
            </form>
          </Surface>
        </div>

        <div style={{ gridColumn: "span 12" }}>
          <Surface title="Notifiche push" subtitle="Le notifiche app arrivano anche quando Condo Charge e chiusa.">
            {profileQuery.loading ? <LoadingState label="Verifica stato push..." /> : null}
            {profileQuery.error ? (
              <ErrorState title="Impossibile caricare lo stato push" message={profileQuery.error} onRetry={profileQuery.refetch} />
            ) : null}

            {profileQuery.data ? (
              <div className="stack">
                <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
                  <StatusBadge tone={pushStatusMeta().tone} label={`Stato: ${pushStatusMeta().label}`} />
                  <StatusBadge tone="neutral" label={`Dispositivi attivi: ${profileQuery.data.push.active_subscriptions}`} />
                </div>

                <div className="section-actions">
                  <button
                    className="btn btn--primary touch-safe"
                    type="button"
                    onClick={enablePushNotifications}
                    disabled={pushLoading || pushState === "unsupported"}
                  >
                    {pushLoading ? "Attivazione..." : "Attiva notifiche"}
                  </button>
                  <button
                    className="btn btn--secondary touch-safe"
                    type="button"
                    onClick={sendPushSelfTest}
                    disabled={pushLoading || pushState !== "active"}
                    data-testid="resident-push-self-test"
                  >
                    {pushLoading ? "Invio..." : "Invia notifica di test"}
                  </button>
                  <button
                    className="btn btn--secondary touch-safe"
                    type="button"
                    onClick={disablePushNotifications}
                    disabled={pushLoading || pushState !== "active"}
                  >
                    {pushLoading ? "Disattivazione..." : "Disattiva notifiche"}
                  </button>
                </div>

                {pushTestDetails ? (
                  <div
                    className="card"
                    style={{ padding: 12 }}
                    data-testid="resident-push-self-test-details"
                  >
                    <div className="muted" style={{ fontSize: 12 }}>
                      delivery_status: {pushTestDetails.delivery_status}
                      <br />
                      delivered_count: {pushTestDetails.delivered_count}
                      <br />
                      timestamp: {pushTestDetails.timestamp}
                    </div>
                  </div>
                ) : null}

                <details className="card" style={{ marginTop: 8 }}>
                  <summary className="card-title" style={{ cursor: "pointer" }}>
                    Diagnostica push
                  </summary>
                  <div className="stack" style={{ paddingTop: 12 }}>
                    <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
                      <StatusBadge tone="neutral" label={`HTTPS: ${pushDiag?.isSecureContext ? "Sì" : "No"}`} />
                      <StatusBadge
                        tone="neutral"
                        label={`Supporto push: ${pushDiag ? (pushDiag.pushSupported ? "Sì" : "No") : "…"}`}
                      />
                      <StatusBadge
                        tone="neutral"
                        label={`Permesso: ${pushDiag ? String(pushDiag.notificationPermissionState) : "…"}`}
                      />
                      <StatusBadge
                        tone="neutral"
                        label={`SW ready: ${pushDiag ? (pushDiag.serviceWorkerReadyResolved ? "Sì" : "No") : "…"}`}
                      />
                      <StatusBadge
                        tone="neutral"
                        label={`VAPID: ${pushDiag ? (pushDiag.vapidPublicKeyRuntimePresent ? pushDiag.vapidPublicKeyRuntimePrefix : "assente") : "…"}`}
                      />
                    </div>

                    <div className="section-actions">
                      <button className="btn btn--secondary touch-safe" type="button" onClick={refreshPushDiagnostics} disabled={pushDiagLoading}>
                        {pushDiagLoading ? "Verifica..." : "Aggiorna diagnostica"}
                      </button>
                      <button
                        className="btn btn--secondary touch-safe"
                        type="button"
                        onClick={async () => {
                          try {
                            const text = JSON.stringify(pushDiag, null, 2);
                            await navigator.clipboard.writeText(text);
                            setPushMessage("Diagnostica copiata.");
                          } catch {
                            setPushError("Impossibile copiare la diagnostica.");
                          }
                        }}
                        disabled={!pushDiag}
                      >
                        Copia
                      </button>
                    </div>

                    {pushDiag ? (
                      <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                        {JSON.stringify(pushDiag, null, 2)}
                      </pre>
                    ) : (
                      <div className="muted">Nessuna diagnostica disponibile.</div>
                    )}
                  </div>
                </details>
              </div>
            ) : null}
          </Surface>
        </div>
      </div>
    </div>
  );
}

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentProfileResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import * as pushService from "../shared/notifications/pushService";
import { ErrorState, LoadingState, PageHead, StatusBadge, Surface } from "../shared/ui";

export default function ResidentProfilePageTelegramV11() {
  const navigate = useNavigate();
  const fetcher = useMemo(() => () => endpoints.residentProfile(), []);
  const query = useQuery<ResidentProfileResponse>(fetcher);

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  const [savingProfile, setSavingProfile] = useState(false);
  const [pushLoading, setPushLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pushState, setPushState] = useState<pushService.BrowserPushState>("disabled");
  const [pushDiag, setPushDiag] = useState<pushService.PushDiagnosticsSnapshot | null>(null);
  const [pushDiagLoading, setPushDiagLoading] = useState(false);

  useEffect(() => {
    if (!query.data) return;
    setEmail(query.data.email ?? "");
    setPhone(query.data.phone_number ?? "");
  }, [query.data]);

  useEffect(() => {
    if (!query.data) return;
    void refreshPushState(query.data.push.subscribed);
  }, [query.data]);

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

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setSavingProfile(true);
    try {
      await endpoints.updateResidentProfile({
        email: email.trim() || null,
        phone_number: phone.trim() || null,
      });
      setMessage("Profilo aggiornato.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare il profilo");
    } finally {
      setSavingProfile(false);
    }
  }

  async function enablePushNotifications() {
    setError(null);
    setMessage(null);
    setPushLoading(true);
    try {
      await refreshPushDiagnostics();
      const permission = await pushService.requestNotificationPermission();
      await refreshPushDiagnostics();
      if (permission !== "granted") {
        setError("Permesso notifiche non concesso.");
        await refreshPushState(false);
        return;
      }
      await pushService.subscribeToPush();
      await refreshPushDiagnostics();
      setMessage("Notifiche push attivate.");
      await query.refetch();
      await refreshPushState(true);
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile attivare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  async function disablePushNotifications() {
    setError(null);
    setMessage(null);
    setPushLoading(true);
    try {
      await pushService.unsubscribeFromPush();
      await refreshPushDiagnostics();
      setMessage("Notifiche push disattivate.");
      await query.refetch();
      await refreshPushState(false);
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile disattivare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  return (
    <div>
      <PageHead
        title="Profilo"
        subtitle="Account e contatti"
        right={
          <button className="btn btn--secondary touch-safe" type="button" onClick={() => navigate("/resident/cambia-password")}>
            Cambia password
          </button>
        }
      />

      {query.loading ? <LoadingState label="Caricamento profilo..." /> : null}
      {query.error ? <ErrorState title="Impossibile caricare il profilo" message={query.error} onRetry={query.refetch} /> : null}
      {error ? <ErrorState title="Operazione non riuscita" message={error} /> : null}
      {message ? <div className="muted">{message}</div> : null}

      {query.data ? (
        <div className="grid">
          <div style={{ gridColumn: "span 12" }}>
            <Surface title="Account" subtitle="Dati essenziali del tuo profilo">
              <div className="row">
                <StatusBadge tone="neutral" label={`Username: ${query.data.username}`} />
              </div>
            </Surface>
          </div>

          <div style={{ gridColumn: "span 12" }}>
            <Surface title="Contatti" subtitle="Aggiorna email e telefono (opzionale)">
              <form className="auth-form" onSubmit={saveProfile}>
                <label className="auth-label">
                  Email
                  <input className="auth-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                </label>
                <label className="auth-label">
                  Telefono (opzionale)
                  <input className="auth-input" value={phone} onChange={(e) => setPhone(e.target.value)} />
                </label>
                <button className="btn btn--primary touch-safe" type="submit" disabled={savingProfile}>
                  {savingProfile ? "Salvataggio..." : "Salva"}
                </button>
              </form>
            </Surface>
          </div>

          <div style={{ gridColumn: "span 12" }}>
            <Surface title="Notifiche" subtitle="Ricevi aggiornamenti anche quando l'app e chiusa">
              <div className="stack">
                <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
                  <StatusBadge tone={pushStatusMeta().tone} label={`Stato: ${pushStatusMeta().label}`} />
                  <StatusBadge tone="neutral" label={`Dispositivi attivi: ${query.data.push.active_subscriptions}`} />
                </div>
                <div className="muted">
                  {pushState === "unsupported"
                    ? "Il tuo browser non supporta le notifiche push web."
                    : "Attiva le notifiche per ricevere avvisi su colonnina disponibile, coda e ricarica completata."}
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
                    onClick={disablePushNotifications}
                    disabled={pushLoading || pushState !== "active"}
                  >
                    {pushLoading ? "Disattivazione..." : "Disattiva notifiche"}
                  </button>
                </div>

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
                            setMessage("Diagnostica copiata.");
                          } catch {
                            setError("Impossibile copiare la diagnostica.");
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
            </Surface>
          </div>
        </div>
      ) : null}
    </div>
  );
}

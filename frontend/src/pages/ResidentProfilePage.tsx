import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentProfileResponse, TelegramLinkIssueResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { EmptyState, ErrorState, LoadingState, PageHead, StatusBadge, Surface, formatDateTime } from "../shared/ui";
import * as pushService from "../shared/notifications/pushService";

export default function ResidentTelegramPage() {
  const fetcher = useMemo(() => () => endpoints.residentProfile(), []);
  const query = useQuery<ResidentProfileResponse>(fetcher);

  const [linking, setLinking] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [telegramIssue, setTelegramIssue] = useState<TelegramLinkIssueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pushLoading, setPushLoading] = useState(false);

  async function issueTelegramLink() {
    setError(null);
    setMessage(null);
    setLinking(true);
    try {
      const payload = await endpoints.issueResidentTelegramLink();
      setTelegramIssue(payload);
      setMessage("Link generato.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile generare il link");
    } finally {
      setLinking(false);
    }
  }

  async function unlinkTelegram() {
    setError(null);
    setMessage(null);
    setUnlinking(true);
    try {
      await endpoints.unlinkResidentTelegram();
      setTelegramIssue(null);
      setMessage("Telegram scollegato.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile scollegare Telegram");
    } finally {
      setUnlinking(false);
    }
  }

  async function enablePushNotifications() {
    setError(null);
    setMessage(null);
    setPushLoading(true);
    try {
      const permission = await pushService.requestNotificationPermission();
      if (permission !== "granted") {
        setError("Permesso notifiche negato");
        return;
      }
      const subscription = await pushService.subscribeToPush();
      if (subscription) {
        // TODO: Send subscription to backend when implemented
        console.log("Push subscription created:", subscription);
        setMessage("Notifiche push abilitate (placeholder).");
      }
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile abilitare le notifiche push");
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
      // TODO: Remove subscription from backend when implemented
      setMessage("Notifiche push disabilitate (placeholder).");
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile disabilitare le notifiche push");
    } finally {
      setPushLoading(false);
    }
  }

  return (
    <div>
      <PageHead title="Telegram" subtitle="Non vuoi installare l’app? Usa CondoChargeBot e ricevi gli aggiornamenti direttamente su Telegram." />

      {query.loading ? <LoadingState label="Caricamento Telegram..." /> : null}
      {query.error ? <ErrorState title="Impossibile caricare Telegram" message={query.error} onRetry={query.refetch} /> : null}
      {error ? <ErrorState title="Operazione non riuscita" message={error} /> : null}
      {message ? <StatusBadge tone="ok" label={message} /> : null}

      <div className="grid">
        <div style={{ gridColumn: "span 12" }}>
          <Surface title="Comandi" subtitle="Provali in chat con il bot" className="surface--accent">
            <div className="list">
              <div className="list-item">
                <div className="list-item__title">/status</div>
                <div className="list-item__meta">Stato colonnine</div>
              </div>
              <div className="list-item">
                <div className="list-item__title">/history</div>
                <div className="list-item__meta">Ultime ricariche</div>
              </div>
              <div className="list-item">
                <div className="list-item__title">/test</div>
                <div className="list-item__meta">Messaggio di prova</div>
              </div>
            </div>
          </Surface>
        </div>

        <div style={{ gridColumn: "span 12" }}>
          <Surface title="Collegamento" subtitle="Collega il tuo account per ricevere aggiornamenti">
            {query.data ? (
              <div className="stack">
                <div className="row">
                  <StatusBadge tone={query.data.telegram.linked ? "ok" : "warn"} label={query.data.telegram.linked ? "Collegato" : "Non collegato"} />
                  <StatusBadge tone="neutral" label={`Collegato il: ${formatDateTime(query.data.telegram.linked_at)}`} />
                </div>

                {telegramIssue?.deep_link_url ? (
                  <a className="btn btn--primary touch-safe" href={telegramIssue.deep_link_url} target="_blank" rel="noreferrer">
                    Apri Telegram
                  </a>
                ) : null}

                {telegramIssue ? <div className="muted">Link valido fino a: {formatDateTime(telegramIssue.expires_at)}</div> : null}

                <div className="section-actions">
                  <button className="btn btn--primary touch-safe" type="button" onClick={issueTelegramLink} disabled={linking}>
                    {linking ? "Collegamento..." : "Collega Telegram"}
                  </button>
                  <button className="btn btn--secondary touch-safe" type="button" onClick={unlinkTelegram} disabled={unlinking || !query.data.telegram.linked}>
                    {unlinking ? "Scollegamento..." : "Scollega"}
                  </button>
                </div>
              </div>
            ) : (
              <EmptyState title="Telegram non disponibile" message="Riprova tra qualche istante." />
            )}
          </Surface>
        </div>

        <div style={{ gridColumn: "span 12" }}>
          <Surface title="Notifiche Push" subtitle="Ricevi aggiornamenti direttamente sul tuo dispositivo (placeholder)">
            {query.data ? (
              <div className="stack">
                <div className="detail-grid">
                  <div className="detail-card kv">
                    <div className="kv__label">Colonnina disponibile</div>
                    <div className="kv__value">{query.data.notification_preferences.station_available ? "Sì" : "No"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Colonnina in uso</div>
                    <div className="kv__value">{query.data.notification_preferences.station_busy ? "Sì" : "No"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Colonnina torna online</div>
                    <div className="kv__value">{query.data.notification_preferences.station_back_online ? "Sì" : "No"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Ricarica completata</div>
                    <div className="kv__value">{query.data.notification_preferences.charging_completed ? "Sì" : "No"}</div>
                  </div>
                </div>
                <div className="muted">
                  Questa è un'anteprima per il supporto alle notifiche push web, non ancora implementato completamente.
                </div>
                <div className="section-actions">
                  <button className="btn btn--primary touch-safe" type="button" onClick={enablePushNotifications} disabled={pushLoading}>
                    {pushLoading ? "Abilitazione..." : "Abilita notifiche push"}
                  </button>
                  <button className="btn btn--secondary touch-safe" type="button" onClick={disablePushNotifications} disabled={pushLoading}>
                    {pushLoading ? "Disabilitazione..." : "Disabilita notifiche push"}
                  </button>
                </div>
              </div>
            ) : (
              <EmptyState title="Notifiche non disponibili" message="Riprova tra qualche istante." />
            )}
          </Surface>
        </div>
      </div>
    </div>
  );
}

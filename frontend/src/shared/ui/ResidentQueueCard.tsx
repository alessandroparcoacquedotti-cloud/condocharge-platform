import { useMemo, useState } from "react";

import { endpoints } from "../api/endpoints";
import type { ResidentQueueStatusResponse } from "../api/types";
import { useQuery } from "../hooks/useQuery";
import { EmptyState, ErrorState, LoadingState, StatusBadge, Surface, formatDateTime } from "./components";

export function ResidentQueueCard() {
  const fetcher = useMemo(() => () => endpoints.residentQueueStatus(), []);
  const query = useQuery<ResidentQueueStatusResponse>(fetcher);
  const [busy, setBusy] = useState<"join" | "leave" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function joinQueue() {
    setBusy("join");
    setActionError(null);
    try {
      await endpoints.joinResidentQueue();
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile entrare in coda");
    } finally {
      setBusy(null);
    }
  }

  async function leaveQueue() {
    setBusy("leave");
    setActionError(null);
    try {
      await endpoints.leaveResidentQueue();
      query.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile uscire dalla coda");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Surface
      title="Coda di attesa"
      subtitle="Accesso ordinato alle colonnine quando la priorita e attiva"
      className="surface--accent"
    >
      {query.loading ? <LoadingState label="Caricamento stato coda…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare la coda" message={query.error} onRetry={query.refetch} /> : null}
      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {query.data ? (
        <div className="stack">
          <div className="row">
            <StatusBadge tone={query.data.queue_enabled ? "ok" : "warn"} label={`Coda abilitata: ${query.data.queue_enabled ? "Si" : "No"}`} />
            <StatusBadge tone={query.data.in_queue ? "ok" : "neutral"} label={`In coda: ${query.data.in_queue ? "Si" : "No"}`} />
          </div>
          <div className="detail-grid">
            <div className="detail-card kv">
              <div className="kv__label">Posizione</div>
              <div className="kv__value">{query.data.position ?? "-"}</div>
            </div>
            <div className="detail-card kv">
              <div className="kv__label">Ingresso</div>
              <div className="kv__value">{formatDateTime(query.data.joined_at)}</div>
            </div>
          </div>
          {!query.data.queue_enabled ? (
            <EmptyState
              title="Coda al momento disattivata"
              message="Puoi comunque controllare lo stato delle colonnine e ricevere aggiornamenti quando la funzione verra attivata."
            />
          ) : null}
          <div className="muted">
            Visualizzi solo la tua posizione personale. La lista dei condomini in coda non viene mostrata.
          </div>
          <div className="section-actions">
            <button className="btn btn--primary touch-safe" type="button" disabled={busy !== null || !query.data.queue_enabled || query.data.in_queue} onClick={joinQueue}>
              {busy === "join" ? "Ingresso…" : "Entra in coda"}
            </button>
            <button className="btn btn-secondary touch-safe" type="button" disabled={busy !== null || !query.data.in_queue} onClick={leaveQueue}>
              {busy === "leave" ? "Uscita…" : "Esci dalla coda"}
            </button>
          </div>
        </div>
      ) : null}
    </Surface>
  );
}

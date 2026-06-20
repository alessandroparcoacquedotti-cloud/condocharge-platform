import { useMemo, useState } from "react";

import { endpoints } from "../api/endpoints";
import type { ResidentQueueStatusResponse } from "../api/types";
import { useQuery } from "../hooks/useQuery";
import { ErrorState, LoadingState, formatDateTime } from "./components";

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
    <div className="card" style={{ gridColumn: "span 6" }}>
      <div className="card-title">Coda di attesa</div>
      {query.loading ? <LoadingState label="Caricamento stato coda…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare la coda" message={query.error} onRetry={query.refetch} /> : null}
      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {query.data ? (
        <div style={{ display: "grid", gap: 10 }}>
          <div><strong>Coda abilitata:</strong> {query.data.queue_enabled ? "Si" : "No"}</div>
          <div><strong>In coda:</strong> {query.data.in_queue ? "Si" : "No"}</div>
          <div><strong>Posizione:</strong> {query.data.position ?? "-"}</div>
          <div><strong>Ingresso:</strong> {formatDateTime(query.data.joined_at)}</div>
          <div className="muted">
            Visualizzi solo la tua posizione personale. La lista dei condomini in coda non viene mostrata.
          </div>
          <div className="row" style={{ justifyContent: "flex-start" }}>
            <button className="btn" type="button" disabled={busy !== null || !query.data.queue_enabled || query.data.in_queue} onClick={joinQueue}>
              {busy === "join" ? "Ingresso…" : "Entra in coda"}
            </button>
            <button className="btn btn-secondary" type="button" disabled={busy !== null || !query.data.in_queue} onClick={leaveQueue}>
              {busy === "leave" ? "Uscita…" : "Esci dalla coda"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

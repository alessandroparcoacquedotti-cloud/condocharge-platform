import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../api/endpoints";
import type { AdminQueueSettingsResponse } from "../api/types";
import { useQuery } from "../hooks/useQuery";
import { ErrorState, LoadingState, formatDateTime } from "./components";

export function AdminQueueSettingsCard() {
  const fetcher = useMemo(() => () => endpoints.adminQueueSettings(), []);
  const query = useQuery<AdminQueueSettingsResponse>(fetcher);
  const [queueEnabled, setQueueEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setQueueEnabled(query.data.queue_enabled);
  }, [query.data]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const payload = await endpoints.updateAdminQueueSettings({ queue_enabled: queueEnabled });
      setQueueEnabled(payload.queue_enabled);
      setSaveMessage("Impostazioni coda aggiornate.");
      query.refetch();
    } catch (err) {
      setSaveError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Salvataggio non riuscito");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ gridColumn: "span 6" }}>
      <div className="card-title">Coda di attesa</div>
      {query.loading ? <LoadingState label="Caricamento impostazioni coda…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare la coda" message={query.error} onRetry={query.refetch} /> : null}
      {saveError ? <ErrorState title="Aggiornamento non riuscito" message={saveError} /> : null}
      {query.data ? (
        <form className="auth-form" onSubmit={onSave}>
          <div className="muted">La coda e disattivata per default fino a validazione operativa.</div>
          <div className="muted">Condomini in attesa: {query.data.waiting_count}</div>
          <div className="muted">Ultimo aggiornamento: {formatDateTime(query.data.updated_at)}</div>
          <label className="row" style={{ justifyContent: "flex-start" }}>
            <input type="checkbox" checked={queueEnabled} onChange={(e) => setQueueEnabled(e.target.checked)} />
            <span>Abilita coda condominiale</span>
          </label>
          <div className="muted">Questa release abilita solo join, leave e posizione personale. Nessuna assegnazione automatica e attiva.</div>
          <button className="btn" type="submit" disabled={saving}>
            {saving ? "Salvataggio…" : "Salva coda"}
          </button>
          {saveMessage ? <div className="muted">{saveMessage}</div> : null}
        </form>
      ) : null}
    </div>
  );
}

import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentNotificationPreferences, ResidentNotificationPreferencesUpdate } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

export default function ResidentNotificationsPage() {
  const fetcher = useMemo(() => () => endpoints.residentNotificationPreferences(), []);
  const query = useQuery<ResidentNotificationPreferences>(fetcher);

  const [values, setValues] = useState<ResidentNotificationPreferencesUpdate>({
    charging_completed: true,
    station_available: true,
    station_busy: false,
    station_back_online: false,
    agent_offline: true,
    agent_recovered: true,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

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

  return (
    <div>
      <PageHead title="Notifiche" subtitle="Preferenze notifiche. Le notifiche push non sono ancora attive: questa sezione prepara la funzionalità." />

      {query.loading ? <LoadingState label="Caricamento preferenze…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare le preferenze" message={query.error} onRetry={query.refetch} /> : null}
      {saveError ? <ErrorState title="Salvataggio non riuscito" message={saveError} /> : null}

      <div className="grid">
        <div className="card" style={{ gridColumn: "span 6" }}>
          <div className="card-title">Preferenze</div>
          <form className="auth-form" onSubmit={onSave}>
            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.charging_completed}
                onChange={(e) => setValues((v) => ({ ...v, charging_completed: e.target.checked }))}
              />
              <span>Ricarica completata</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “La tua auto ha terminato la ricarica.”
            </div>

            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.station_available}
                onChange={(e) => setValues((v) => ({ ...v, station_available: e.target.checked }))}
              />
              <span>Colonnina disponibile</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “La colonnina è libera.”
            </div>

            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.station_busy}
                onChange={(e) => setValues((v) => ({ ...v, station_busy: e.target.checked }))}
              />
              <span>Colonnina occupata</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “La colonnina è occupata.”
            </div>

            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.station_back_online}
                onChange={(e) => setValues((v) => ({ ...v, station_back_online: e.target.checked }))}
              />
              <span>Colonnina tornata online</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “Una colonnina è tornata online.”
            </div>

            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.agent_offline}
                onChange={(e) => setValues((v) => ({ ...v, agent_offline: e.target.checked }))}
              />
              <span>Agente offline</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “Il mini-PC agente non risponde.”
            </div>

            <label className="row" style={{ justifyContent: "flex-start" }}>
              <input
                type="checkbox"
                checked={values.agent_recovered}
                onChange={(e) => setValues((v) => ({ ...v, agent_recovered: e.target.checked }))}
              />
              <span>Agente ripristinato</span>
            </label>
            <div className="muted" style={{ marginTop: -6, fontSize: 12 }}>
              “Il mini-PC agente e tornato operativo.”
            </div>

            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Salvataggio…" : "Salva"}
            </button>
            {saveMessage ? <div className="muted">{saveMessage}</div> : null}
          </form>
        </div>

        <div className="card" style={{ gridColumn: "span 6" }}>
          <div className="card-title">Attività</div>
          <div className="muted">
            Nessuna notifica disponibile. Questa sezione mostrerà gli eventi quando la consegna notifiche sarà attivata.
          </div>
        </div>
      </div>
    </div>
  );
}

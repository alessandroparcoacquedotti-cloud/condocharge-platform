import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentNotificationPreferencesUpdate, ResidentProfileResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

export default function ResidentProfilePage() {
  const navigate = useNavigate();
  const fetcher = useMemo(() => () => endpoints.residentProfile(), []);
  const query = useQuery<ResidentProfileResponse>(fetcher);

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [prefs, setPrefs] = useState<ResidentNotificationPreferencesUpdate>({
    charging_completed: true,
    station_available: true,
    station_back_online: false,
  });

  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setEmail(query.data.email ?? "");
    setPhone(query.data.phone_number ?? "");
    setPrefs({
      charging_completed: query.data.notification_preferences.charging_completed,
      station_available: query.data.notification_preferences.station_available,
      station_back_online: query.data.notification_preferences.station_back_online,
    });
  }, [query.data]);

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

  async function savePrefs(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setSavingPrefs(true);
    try {
      await endpoints.updateResidentNotificationPreferences(prefs);
      setMessage("Preferenze aggiornate.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare le preferenze");
    } finally {
      setSavingPrefs(false);
    }
  }

  return (
    <div>
      <PageHead title="Profilo" subtitle="Dati personali, contatti e preferenze notifiche" right={<button className="btn" type="button" onClick={() => navigate("/resident/cambia-password")}>Cambia password</button>} />

      {query.loading ? <LoadingState label="Caricamento profilo…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare il profilo" message={query.error} onRetry={query.refetch} /> : null}
      {error ? <ErrorState title="Operazione non riuscita" message={error} /> : null}
      {message ? <div className="muted">{message}</div> : null}

      {query.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Dati</div>
            <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
              <span className="pill">
                Nome: <span className="muted">{[query.data.first_name, query.data.last_name].filter(Boolean).join(" ") || "-"}</span>
              </span>
              <span className="pill">
                Unità: <span className="muted">{query.data.apartment_or_unit ?? "-"}</span>
              </span>
              <span className="pill">
                Username: <span className="muted">{query.data.username}</span>
              </span>
            </div>
          </div>

          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Contatti</div>
            <form className="auth-form" onSubmit={saveProfile}>
              <label className="auth-label">
                Email
                <input className="auth-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="auth-label">
                Telefono (opzionale)
                <input className="auth-input" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </label>
              <button className="btn" type="submit" disabled={savingProfile}>
                {savingProfile ? "Salvataggio…" : "Salva"}
              </button>
            </form>
          </div>

          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Tessere RFID collegate</div>
            {query.data.linked_cards.length ? (
              <div style={{ display: "grid", gap: 8 }}>
                {query.data.linked_cards.map((c) => (
                  <div key={c.id} className="pill" style={{ justifyContent: "space-between" }}>
                    <span>{c.name ?? "Tessera"}</span>
                    <span className="muted">{c.rfid_id}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted">Nessuna tessera collegata al tuo account.</div>
            )}
          </div>

          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Preferenze notifiche</div>
            <form className="auth-form" onSubmit={savePrefs}>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.charging_completed}
                  onChange={(e) => setPrefs((v) => ({ ...v, charging_completed: e.target.checked }))}
                />
                <span>Ricarica completata</span>
              </label>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.station_available}
                  onChange={(e) => setPrefs((v) => ({ ...v, station_available: e.target.checked }))}
                />
                <span>Colonnina disponibile</span>
              </label>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.station_back_online}
                  onChange={(e) => setPrefs((v) => ({ ...v, station_back_online: e.target.checked }))}
                />
                <span>Colonnina tornata online</span>
              </label>
              <button className="btn" type="submit" disabled={savingPrefs}>
                {savingPrefs ? "Salvataggio…" : "Salva"}
              </button>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}


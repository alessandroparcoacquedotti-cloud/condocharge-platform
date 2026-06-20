import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import type { TelegramLinkIssueResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

type ResidentNotificationPreferencesUpdate = {
  charging_completed: boolean;
  station_available: boolean;
  station_busy: boolean;
  station_back_online: boolean;
  agent_offline: boolean;
  agent_recovered: boolean;
};

type ResidentProfileResponse = {
  username: string;
  first_name: string | null;
  last_name: string | null;
  apartment_or_unit: string | null;
  email: string | null;
  phone_number: string | null;
  linked_cards: Array<{ id: number; rfid_id: string; name: string | null }>;
  notification_preferences: ResidentNotificationPreferencesUpdate;
  telegram: {
    linked: boolean;
    chat_id: string | null;
    telegram_username: string | null;
    linked_at: string | null;
  };
};

export default function ResidentProfilePage() {
  const navigate = useNavigate();
  const fetcher = useMemo(
    () => async () => (await endpoints.residentProfile()) as ResidentProfileResponse,
    [],
  );
  const query = useQuery<ResidentProfileResponse>(fetcher);

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [prefs, setPrefs] = useState<ResidentNotificationPreferencesUpdate>({
    charging_completed: true,
    station_available: true,
     station_busy: false,
    station_back_online: false,
    agent_offline: true,
    agent_recovered: true,
  });

  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [linkingTelegram, setLinkingTelegram] = useState(false);
  const [unlinkingTelegram, setUnlinkingTelegram] = useState(false);
  const [telegramIssue, setTelegramIssue] = useState<TelegramLinkIssueResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setEmail(query.data.email ?? "");
    setPhone(query.data.phone_number ?? "");
    setPrefs({
      charging_completed: query.data.notification_preferences.charging_completed,
      station_available: query.data.notification_preferences.station_available,
      station_busy: query.data.notification_preferences.station_busy,
      station_back_online: query.data.notification_preferences.station_back_online,
      agent_offline: query.data.notification_preferences.agent_offline,
      agent_recovered: query.data.notification_preferences.agent_recovered,
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

  async function issueTelegramLink() {
    setError(null);
    setMessage(null);
    setLinkingTelegram(true);
    try {
      const payload = await endpoints.issueResidentTelegramLink();
      setTelegramIssue(payload);
      setMessage("Link Telegram generato.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile generare il link Telegram");
    } finally {
      setLinkingTelegram(false);
    }
  }

  async function unlinkTelegram() {
    setError(null);
    setMessage(null);
    setUnlinkingTelegram(true);
    try {
      await endpoints.unlinkResidentTelegram();
      setTelegramIssue(null);
      setMessage("Telegram scollegato.");
      query.refetch();
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile scollegare Telegram");
    } finally {
      setUnlinkingTelegram(false);
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
                  checked={prefs.station_busy}
                  onChange={(e) => setPrefs((v) => ({ ...v, station_busy: e.target.checked }))}
                />
                <span>Colonnina occupata</span>
              </label>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.station_back_online}
                  onChange={(e) => setPrefs((v) => ({ ...v, station_back_online: e.target.checked }))}
                />
                <span>Colonnina tornata online</span>
              </label>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.agent_offline}
                  onChange={(e) => setPrefs((v) => ({ ...v, agent_offline: e.target.checked }))}
                />
                <span>Agente offline</span>
              </label>
              <label className="row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={prefs.agent_recovered}
                  onChange={(e) => setPrefs((v) => ({ ...v, agent_recovered: e.target.checked }))}
                />
                <span>Agente ripristinato</span>
              </label>
              <button className="btn" type="submit" disabled={savingPrefs}>
                {savingPrefs ? "Salvataggio…" : "Salva"}
              </button>
            </form>
          </div>

          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Telegram</div>
            <div style={{ display: "grid", gap: 8 }}>
              <div><strong>Stato:</strong> {query.data.telegram.linked ? "Collegato" : "Non collegato"}</div>
              <div className="muted">Chat ID: {query.data.telegram.chat_id ?? "-"}</div>
              <div className="muted">Username Telegram: {query.data.telegram.telegram_username ?? "-"}</div>
              <div className="muted">Collegato il: {query.data.telegram.linked_at ?? "-"}</div>
              {telegramIssue?.deep_link_url ? (
                <a href={telegramIssue.deep_link_url} target="_blank" rel="noreferrer">
                  Apri il bot Telegram
                </a>
              ) : null}
              {telegramIssue ? <div className="muted">Link valido fino a: {telegramIssue.expires_at}</div> : null}
              <div className="muted">Comandi disponibili dopo il collegamento: /help, /status, /history, /test</div>
            </div>
            <div className="row" style={{ justifyContent: "flex-start", marginTop: 12 }}>
              <button className="btn" type="button" onClick={issueTelegramLink} disabled={linkingTelegram}>
                {linkingTelegram ? "Generazione…" : "Genera link Telegram"}
              </button>
              <button className="btn btn-secondary" type="button" onClick={unlinkTelegram} disabled={unlinkingTelegram || !query.data.telegram.linked}>
                {unlinkingTelegram ? "Scollegamento…" : "Scollega Telegram"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

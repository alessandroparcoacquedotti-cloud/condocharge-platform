import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentProfileResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, StatusBadge, Surface } from "../shared/ui";

export default function ResidentProfilePageTelegramV11() {
  const navigate = useNavigate();
  const fetcher = useMemo(() => () => endpoints.residentProfile(), []);
  const query = useQuery<ResidentProfileResponse>(fetcher);

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  const [savingProfile, setSavingProfile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setEmail(query.data.email ?? "");
    setPhone(query.data.phone_number ?? "");
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
        </div>
      ) : null}
    </div>
  );
}

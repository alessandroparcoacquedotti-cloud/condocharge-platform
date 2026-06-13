import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import type { InvitationStatusResponse } from "../shared/api/types";
import { ErrorState, LoadingState, PageHead } from "../shared/ui";

export default function InvitationPage() {
  const navigate = useNavigate();
  const { token = "" } = useParams();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<InvitationStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    endpoints
      .invitationStatus(token)
      .then((resp) => {
        if (cancelled) return;
        setStatus(resp);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile validare l'invito");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!status?.valid) return;
    setError(null);
    setMessage(null);
    if (password !== confirmPassword) {
      setError("Le password non coincidono.");
      return;
    }
    setSubmitting(true);
    try {
      await endpoints.completeInvitation(token, { password });
      setMessage("Password impostata con successo. Reindirizzamento al login…");
      window.setTimeout(() => navigate("/login", { replace: true }), 1200);
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile completare l'invito");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Verifica invito…" />;
  }

  if (error) {
    return <ErrorState title="Invito non disponibile" message={error} />;
  }

  if (!status?.valid) {
    return (
      <div>
        <PageHead title="Invito non valido" subtitle="Il link potrebbe essere scaduto, gia usato o sostituito da un invito piu recente." />
        <div className="card" style={{ maxWidth: 560 }}>
          <div className="muted">Chiedi all'amministratore di inviarti un nuovo invito CondoCharge.</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHead
        title="Attiva il tuo account"
        subtitle={`Condominio: ${status.condominium_name ?? "-"} · Username: ${status.username ?? "-"}`}
      />

      {error ? <ErrorState title="Operazione non riuscita" message={error} /> : null}

      <div className="card" style={{ maxWidth: 560 }}>
        <form className="auth-form" onSubmit={onSubmit}>
          <div className="muted">
            Il link scade il {status.expires_at ? new Date(status.expires_at).toLocaleString() : "-"}.
          </div>
          <label className="auth-label">
            Nuova password
            <input
              className="auth-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <label className="auth-label">
            Conferma password
            <input
              className="auth-input"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <button className="btn" type="submit" disabled={submitting || !password || !confirmPassword}>
            {submitting ? "Attivazione…" : "Attiva account"}
          </button>
          {message ? <div className="muted">{message}</div> : null}
        </form>
      </div>
    </div>
  );
}

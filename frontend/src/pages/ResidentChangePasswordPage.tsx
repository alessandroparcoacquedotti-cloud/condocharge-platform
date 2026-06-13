import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { endpoints } from "../shared/api/endpoints";
import { useAuth } from "../shared/auth/AuthProvider";
import { ErrorState, PageHead } from "../shared/ui";

export default function ResidentChangePasswordPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (newPassword !== confirmPassword) {
      setError("Le password non coincidono.");
      return;
    }
    setSubmitting(true);
    try {
      const updated = await endpoints.changePassword({ current_password: currentPassword, new_password: newPassword });
      auth.updateUser(updated);
      setMessage("Password aggiornata.");
      navigate("/resident/stato-colonnine", { replace: true });
    } catch (err) {
      setError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare la password");
    } finally {
      setSubmitting(false);
    }
  }

  const forced = auth.user?.role === "resident" && !!auth.user.must_change_password;

  return (
    <div>
      <PageHead
        title="Cambia password"
        subtitle={forced ? "Per continuare è necessario impostare una nuova password." : "Aggiorna la password del tuo account."}
      />

      {error ? <ErrorState title="Operazione non riuscita" message={error} /> : null}

      <div className="card" style={{ maxWidth: 520 }}>
        <form className="auth-form" onSubmit={onSubmit}>
          <label className="auth-label">
            Password attuale
            <input
              className="auth-input"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <label className="auth-label">
            Nuova password
            <input
              className="auth-input"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <label className="auth-label">
            Conferma nuova password
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

          <button className="btn" type="submit" disabled={submitting || !currentPassword || !newPassword || !confirmPassword}>
            {submitting ? "Salvataggio…" : "Salva"}
          </button>
          {message ? <div className="muted">{message}</div> : null}
        </form>
      </div>
    </div>
  );
}


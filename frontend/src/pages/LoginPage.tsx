import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../shared/auth/AuthProvider";
import { env } from "../shared/config/env";
import { ErrorState } from "../shared/ui";

export default function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = searchParams.get("next") ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(() => username.trim() && password, [username, password]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const defaultCondominium = env.defaultCondominiumName.trim();
      const payload = {
        username: username.trim(),
        password,
        condominium: defaultCondominium ? defaultCondominium : undefined,
      };
      console.log("LOGIN_RUNTIME", {
        origin: window.location.origin,
        apiBaseUrl: env.apiBaseUrl,
        defaultCondominiumName: env.defaultCondominiumName,
      });
      console.log("LOGIN_START", payload);
      await auth.login(payload);
      navigate(next, { replace: true });
    } catch (err) {
      console.error("LOGIN_EXCEPTION", {
        raw: err,
        name: err instanceof Error ? err.name : undefined,
        message: err instanceof Error ? err.message : String(err),
        stack: err instanceof Error ? err.stack : undefined,
      });
      const message = typeof err === "object" && err && "message" in err ? String((err as any).message) : "Login failed";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card card">
        <div className="auth-hero">
          <div className="brand">
            <div className="brand__mark" aria-hidden="true">
              C
            </div>
            <div className="brand__copy">
              <div className="brand__eyebrow">Premium EV App</div>
              <div className="auth-title">CondoCharge</div>
            </div>
          </div>
          <p className="auth-subtitle">Accedi per controllare disponibilita delle colonnine, ricariche e consumi in un'unica esperienza mobile.</p>
          <div className="row">
            <span className="pill">{env.defaultCondominiumName}</span>
            <span className="pill">Web app installabile</span>
          </div>
        </div>

        {error ? <ErrorState title="Accesso non riuscito" message={error} /> : null}

        <form className="auth-form" onSubmit={onSubmit}>
          <label className="auth-label">
            Nome utente
            <input
              className="auth-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="auth-label">
            Password
            <input
              className="auth-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <button className="btn auth-submit touch-safe" type="submit" disabled={!canSubmit || submitting}>
            {submitting ? "Accesso in corso…" : "Accedi"}
          </button>
        </form>
      </div>
    </div>
  );
}

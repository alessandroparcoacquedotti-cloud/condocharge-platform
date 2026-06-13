import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export function RequireAuth(props: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isLoading) {
    return <div className="auth-loading">Caricamento…</div>;
  }

  if (!auth.user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <>{props.children}</>;
}

export function RequireRole(props: { allow: string[]; children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isLoading) {
    return <div className="auth-loading">Caricamento…</div>;
  }

  if (!auth.user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  if (!props.allow.includes(auth.user.role)) {
    return <Navigate to="/" replace />;
  }

  return <>{props.children}</>;
}

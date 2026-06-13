import { ReactNode } from "react";

const LOCALE = "it-IT";
const DISPLAY_TIMEZONE = "Europe/Rome";

export function PageHead(props: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{props.title}</h1>
        {props.subtitle ? <p className="page-subtitle">{props.subtitle}</p> : null}
      </div>
      {props.right ? <div className="row">{props.right}</div> : null}
    </div>
  );
}

export function LoadingState(props: { label?: string }) {
  return (
    <div className="row">
      <div className="spinner" aria-hidden="true" />
      <div className="muted">{props.label ?? "Caricamento…"}</div>
    </div>
  );
}

export function ErrorState(props: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="error-box">
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{props.title ?? "Errore"}</div>
      <div className="muted" style={{ marginBottom: props.onRetry ? 10 : 0 }}>
        {props.message}
      </div>
      {props.onRetry ? (
        <button className="btn" type="button" onClick={props.onRetry}>
          Riprova
        </button>
      ) : null}
    </div>
  );
}

export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}) {
  return new Intl.NumberFormat(LOCALE, options).format(value);
}

export function formatCurrencyEur(value: number, options: Intl.NumberFormatOptions = {}) {
  return new Intl.NumberFormat(LOCALE, { style: "currency", currency: "EUR", ...options }).format(value);
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat(LOCALE, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: DISPLAY_TIMEZONE,
  }).format(d);
}

export function formatAgeFromNow(value: string | null | undefined, now: Date = new Date()) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  const diffMs = Math.max(0, now.getTime() - d.getTime());
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `Aggiornato ${seconds} secondi fa`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Aggiornato ${minutes} minuti fa`;
  const hours = Math.floor(minutes / 60);
  return `Aggiornato ${hours} ore fa`;
}

export function formatKwhFromWh(wh: number | null | undefined) {
  if (wh == null) return "-";
  return formatNumber(wh / 1000, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

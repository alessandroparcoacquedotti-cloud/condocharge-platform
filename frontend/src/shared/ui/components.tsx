import { ReactNode } from "react";

const LOCALE = "it-IT";
const DISPLAY_TIMEZONE = "Europe/Rome";

type Tone = "neutral" | "ok" | "warn" | "danger";

export function WallboxIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Wallbox main body */}
      <rect x="14" y="8" width="36" height="48" rx="6" fill="#14233d" />
      <rect x="16" y="10" width="32" height="44" rx="5" fill="#ffffff" />
      
      {/* Cable/connector */}
      <path
        d="M44 36C48 36 50 34 50 30C50 26 48 24 44 24"
        stroke="#14233d"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx="50" cy="30" r="4" fill="#14233d" />
      
      {/* Indicator light */}
      <circle cx="32" cy="20" r="3" fill="#18a565" />
      
      {/* Socket outline */}
      <rect x="24" y="32" width="16" height="12" rx="2" stroke="#14233d" strokeWidth="2" />
    </svg>
  );
}

export function PageHead(props: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="page-head__copy">
        <h1 className="page-title">{props.title}</h1>
        {props.subtitle ? <p className="page-subtitle">{props.subtitle}</p> : null}
      </div>
      {props.right ? <div className="row">{props.right}</div> : null}
    </div>
  );
}

export function Surface(props: {
  title?: string;
  subtitle?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={props.className ? `surface ${props.className}` : "surface"}>
      {props.title || props.subtitle || props.aside ? (
        <div className="surface__header">
          <div className="stack" style={{ gap: 4 }}>
            {props.title ? <h2 className="surface__title">{props.title}</h2> : null}
            {props.subtitle ? <p className="surface__subtitle">{props.subtitle}</p> : null}
          </div>
          {props.aside ? <div className="row">{props.aside}</div> : null}
        </div>
      ) : null}
      {props.children}
    </section>
  );
}

export function MetricCard(props: {
  label: string;
  value: ReactNode;
  meta?: ReactNode;
  icon?: string;
  accent?: boolean;
  className?: string;
}) {
  const classes = ["card", "metric-card"];
  if (props.accent) classes.push("metric-card--accent");
  if (props.className) classes.push(props.className);
  return (
    <section className={classes.join(" ")}>
      <div className="metric-card__top">
        <div className="metric-card__label">{props.label}</div>
        {props.icon ? <div className="metric-card__icon" aria-hidden="true">{props.icon}</div> : null}
      </div>
      <div className="metric-card__value">{props.value}</div>
      {props.meta ? <div className="metric-card__meta">{props.meta}</div> : null}
    </section>
  );
}

export function StatusBadge(props: { label: ReactNode; tone?: Tone }) {
  const tone = props.tone ?? "neutral";
  return <span className={`status-badge status-badge--${tone}`}>{props.label}</span>;
}

export function LoadingState(props: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <div className="loading-state__row">
        <div className="spinner" aria-hidden="true" />
        <div className="muted">{props.label ?? "Caricamento..."}</div>
      </div>
    </div>
  );
}

export function EmptyState(props: { title?: string; message: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-state__title">{props.title ?? "Nessun dato disponibile"}</div>
      <div className="empty-state__message">{props.message}</div>
      {props.action ? <div className="row">{props.action}</div> : null}
    </div>
  );
}

export function ErrorState(props: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="error-box">
      <div className="error-box__title">{props.title ?? "Errore"}</div>
      <div className="muted">{props.message}</div>
      {props.onRetry ? (
        <button className="btn btn--secondary" type="button" onClick={props.onRetry}>
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

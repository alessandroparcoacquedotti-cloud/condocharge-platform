import type { AgentStatusResponse } from "../api/types";
import { StatusBadge, formatAgeFromNow, formatDateTime } from "./components";

function getHealthLabel(healthColor: string, online: boolean) {
  if (healthColor === "green") return "Operativo";
  if (healthColor === "yellow") return "Attenzione";
  return online ? "Attenzione" : "Offline";
}

function formatUptimeSeconds(value: number | null | undefined) {
  if (value == null) return "-";
  const seconds = Math.max(0, Math.floor(value));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}g ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function AgentStatusCard(props: { status: AgentStatusResponse }) {
  const { status } = props;
  const statusClass =
    status.health_color === "green"
      ? "is-green"
      : status.health_color === "yellow"
        ? "is-yellow"
        : "is-red";

  return (
    <div className="card hero-card" style={{ gridColumn: "span 5" }}>
      <div className="surface__header">
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="surface__title">Stato agente</h2>
          <p className="surface__subtitle">Telemetria live del servizio di raccolta dati</p>
        </div>
        <StatusBadge
          tone={status.health_color === "green" ? "ok" : status.health_color === "yellow" ? "warn" : "danger"}
          label={getHealthLabel(status.health_color, status.online)}
        />
      </div>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div className="row">
            <span aria-label={`agent-${status.health_color}`} className={`status-dot ${statusClass}`} />
            <div style={{ fontWeight: 800, color: "var(--text-strong)" }}>{status.online ? "Agente online" : "Agente offline"}</div>
          </div>
          <span className="pill">
            Heartbeat: <span className="muted">{formatAgeFromNow(status.last_heartbeat)}</span>
          </span>
        </div>

        <div className="detail-grid">
          <div className="detail-card kv">
            <div className="kv__label">Agent ID</div>
            <div className="kv__value">{status.agent_id ?? "-"}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Hostname</div>
            <div className="kv__value">{status.hostname ?? "-"}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Versione</div>
            <div className="kv__value">{status.agent_version ?? "-"}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Ultimo heartbeat</div>
            <div className="kv__value">{formatDateTime(status.last_heartbeat)}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Heartbeat inviato</div>
            <div className="kv__value">{formatDateTime(status.last_heartbeat_sent_at)}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Ultimo aggiornamento colonnine</div>
            <div className="kv__value">{formatDateTime(status.last_station_update)}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Ultimo import sessioni</div>
            <div className="kv__value">{formatDateTime(status.last_session_import)}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Avvio servizio</div>
            <div className="kv__value">{formatDateTime(status.agent_started_at)}</div>
          </div>
          <div className="detail-card kv">
            <div className="kv__label">Uptime servizio</div>
            <div className="kv__value">{formatUptimeSeconds(status.service_uptime_seconds)}</div>
          </div>
        </div>

        <div className="list">
          <div className="list-item">
            <div className="list-item__title">Heartbeat count:</div>
            <div className="list-item__title">{status.heartbeat_count}</div>
          </div>
          <div className="list-item">
            <div className="list-item__title">Polling count:</div>
            <div className="list-item__title">{status.polling_count}</div>
          </div>
          <div className="list-item">
            <div className="list-item__title">Import count:</div>
            <div className="list-item__title">{status.import_count}</div>
          </div>
          <div className="list-item">
            <div className="list-item__title">Retry count:</div>
            <div className="list-item__title">{status.retry_count}</div>
          </div>
          <div className="list-item">
            <div className="list-item__title">Failure count:</div>
            <div className="list-item__title">{status.failure_count}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

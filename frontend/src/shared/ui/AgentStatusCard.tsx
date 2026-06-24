import type { AgentStatusResponse } from "../api/types";
import { formatAgeFromNow, formatDateTime } from "./components";

function getHealthLabel(healthColor: string, online: boolean) {
  if (healthColor === "green") return "Operativo";
  if (healthColor === "yellow") return "Attenzione";
  return online ? "Attenzione" : "Offline";
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
    <div className="card" style={{ gridColumn: "span 5" }}>
      <div className="card-title">Stato agente</div>
      <div style={{ display: "grid", gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div className="row">
            <span aria-label={`agent-${status.health_color}`} className={`status-dot ${statusClass}`} />
            <div style={{ fontWeight: 800 }}>{status.online ? "Agente online" : "Agente offline"}</div>
          </div>
          <span className={`pill ${status.health_color === "green" ? "is-ok" : status.health_color === "yellow" ? "is-warn" : "is-danger"}`}>
            {getHealthLabel(status.health_color, status.online)}
          </span>
        </div>

        <div className="row">
          <span className="pill">
            Agent ID: <span className="muted">{status.agent_id ?? "-"}</span>
          </span>
          <span className="pill">
            Heartbeat: <span className="muted">{formatAgeFromNow(status.last_heartbeat)}</span>
          </span>
        </div>

        <div style={{ display: "grid", gap: 8 }}>
          <div className="row">
            <span className="pill">
              Ultimo heartbeat: <span className="muted">{formatDateTime(status.last_heartbeat)}</span>
            </span>
            <span className="pill">
              Ultimo aggiornamento colonnine: <span className="muted">{formatDateTime(status.last_station_update)}</span>
            </span>
          </div>
          <div className="row">
            <span className="pill">
              Ultimo import sessioni: <span className="muted">{formatDateTime(status.last_session_import)}</span>
            </span>
          </div>
        </div>

        <div className="row">
          <span className="pill">
            Heartbeat count: <span className="muted">{status.heartbeat_count}</span>
          </span>
          <span className="pill">
            Polling count: <span className="muted">{status.polling_count}</span>
          </span>
          <span className="pill">
            Import count: <span className="muted">{status.import_count}</span>
          </span>
          <span className="pill">
            Retry count: <span className="muted">{status.retry_count}</span>
          </span>
          <span className="pill">
            Failure count: <span className="muted">{status.failure_count}</span>
          </span>
        </div>
      </div>
    </div>
  );
}

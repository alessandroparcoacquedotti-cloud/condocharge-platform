import { useMemo } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { SystemHealthResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { AgentStatusCard } from "../shared/ui/AgentStatusCard";
import { ErrorState, LoadingState, PageHead, StatusBadge, formatDateTime } from "../shared/ui";

function badge(ok: boolean, labelOk: string, labelBad: string) {
  return <StatusBadge tone={ok ? "ok" : "danger"} label={ok ? labelOk : labelBad} />;
}

export default function AdminSystemHealthPage() {
  const fetcher = useMemo(() => () => endpoints.adminSystemHealth(), []);
  const query = useQuery<SystemHealthResponse>(fetcher, { refetchIntervalMs: 5000 });

  return (
    <div>
      <PageHead title="System Health" subtitle="Stato backend, integrazioni e telemetria agente" />

      {query.loading ? <LoadingState label="Caricamento stato sistema…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare lo stato sistema" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <>
          <div className="card" style={{ marginBottom: 12 }}>
            <div className="surface__header">
              <div className="stack" style={{ gap: 4 }}>
                <h2 className="surface__title">Snapshot</h2>
                <p className="surface__subtitle">Aggiornato: {formatDateTime(query.data.server_time)}</p>
              </div>
            </div>

            <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
              {badge(query.data.backend_ok, "Backend OK", "Backend KO")}
              {badge(query.data.database_ok, "Database OK", "Database KO")}
              {badge(query.data.railway_dns_ok, "Railway DNS OK", "Railway DNS KO")}
              {badge(query.data.telegram_configured, "Telegram configurato", "Telegram non configurato")}
              {badge(query.data.push_configured, "Push configurato", "Push non configurato")}
              <span className="pill">Push subscriptions: {query.data.push_active_subscriptions}</span>
            </div>
          </div>

          <div className="grid">
            <AgentStatusCard status={query.data.agent_status} />
          </div>
        </>
      ) : null}
    </div>
  );
}

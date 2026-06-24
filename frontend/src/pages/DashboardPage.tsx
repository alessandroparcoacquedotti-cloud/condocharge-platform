import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import { useQuery } from "../shared/hooks/useQuery";
import { AgentStatusCard } from "../shared/ui/AgentStatusCard";
import {
  DateRange,
  DateRangeControls,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHead,
  StatusBadge,
  Surface,
  buildPresetRange,
  formatDateTime,
  formatKwhFromWh,
  formatNumber,
  toApiRange,
} from "../shared/ui";

export default function DashboardPage() {
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last7", fromDate: null, toDate: null }));

  const fetcher = useMemo(() => () => endpoints.dashboardSummary(toApiRange(range)), [range]);
  const summaryQuery = useQuery(fetcher);
  const alerts = useMemo(() => {
    if (!summaryQuery.data) return [];
    const next: Array<{ tone: "ok" | "warn" | "danger"; label: string; message: string }> = [];
    if (!summaryQuery.data.agent_status.online) {
      next.push({
        tone: "danger",
        label: "Agente offline",
        message: "La sincronizzazione live e ferma: controlla heartbeat e importazioni.",
      });
    } else if (summaryQuery.data.agent_status.health_color === "yellow") {
      next.push({
        tone: "warn",
        label: "Agente da verificare",
        message: "Sono presenti warning o ritardi recenti nella telemetria.",
      });
    } else {
      next.push({
        tone: "ok",
        label: "Sistema operativo",
        message: "Agente e dashboard risultano stabili nel periodo selezionato.",
      });
    }
    if (!summaryQuery.data.latest_session) {
      next.push({
        tone: "warn",
        label: "Nessuna ricarica recente",
        message: "Nel periodo selezionato non risultano nuove sessioni importate.",
      });
    }
    return next;
  }, [summaryQuery.data]);

  return (
    <div>
      <PageHead
        title="Panoramica"
        subtitle="Indicatori basati sulle ricariche importate da Green'Up"
        right={
          <>
            <DateRangeControls
              range={range}
              onChange={(next) => {
                if (next.preset !== "custom") {
                  const preset = buildPresetRange(next.preset);
                  setRange({ preset: next.preset, fromDate: preset.fromDate, toDate: preset.toDate });
                } else {
                  setRange(next);
                }
              }}
            />
            <StatusBadge tone="neutral" label="/api/v1/dashboard/summary" />
          </>
        }
      />

      {summaryQuery.loading ? <LoadingState label="Caricamento panoramica…" /> : null}
      {summaryQuery.error ? (
        <ErrorState title="Impossibile caricare la panoramica" message={summaryQuery.error} onRetry={summaryQuery.refetch} />
      ) : null}

      {summaryQuery.data ? (
        <div className="grid">
          <div style={{ gridColumn: "span 12" }}>
            <Surface
              title="Overview operativa"
              subtitle="KPI puliti per una lettura immediata di stazioni, utenti e sessioni"
              className="surface--accent hero-card"
            >
              <div className="grid">
                <MetricCard label="Ricariche" value={summaryQuery.data.total_sessions} meta="Sessioni nel periodo" icon="01" accent />
                <MetricCard
                  label="Energia"
                  value={`${formatNumber(summaryQuery.data.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`}
                  meta={`${formatNumber(summaryQuery.data.total_energy_wh)} Wh`}
                  icon="kWh"
                />
                <MetricCard label="Utenti attivi" value={summaryQuery.data.total_users} meta="Residenti con dati disponibili" icon="USR" />
                <MetricCard label="Colonnine attive" value={summaryQuery.data.total_stations} meta="Stazioni monitorate" icon="EV" />
              </div>
            </Surface>
          </div>

          <div style={{ gridColumn: "span 7" }}>
            <Surface title="Alert" subtitle="Segnali prioritari per l'operativita giornaliera">
              <div className="list">
                {alerts.map((alert) => (
                  <div key={alert.label} className="list-item">
                    <div>
                      <div className="list-item__title">{alert.label}</div>
                      <div className="list-item__meta">{alert.message}</div>
                    </div>
                    <StatusBadge tone={alert.tone} label={alert.tone === "ok" ? "OK" : alert.tone === "warn" ? "CHECK" : "URGENTE"} />
                  </div>
                ))}
              </div>
            </Surface>
          </div>

          <AgentStatusCard status={summaryQuery.data.agent_status} />

          <div style={{ gridColumn: "span 5" }}>
            <Surface title="Ultima ricarica" subtitle="Evento piu recente importato">
              {summaryQuery.data.latest_session ? (
                <div className="stack">
                  <div className="row">
                    <StatusBadge tone="ok" label="Importata" />
                    <StatusBadge tone="neutral" label={summaryQuery.data.latest_session.station?.host ?? `#${summaryQuery.data.latest_session.station_id}`} />
                  </div>
                  <div className="detail-grid">
                    <div className="detail-card kv">
                      <div className="kv__label">Fine sessione</div>
                      <div className="kv__value">{formatDateTime(summaryQuery.data.latest_session.end_time)}</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Energia</div>
                      <div className="kv__value">{formatKwhFromWh(summaryQuery.data.latest_session.energy_wh)} kWh</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Durata</div>
                      <div className="kv__value">{summaryQuery.data.latest_session.total_minutes} min</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Utente</div>
                      <div className="kv__value">
                        {summaryQuery.data.latest_session.rfid_user?.name ?? summaryQuery.data.latest_session.rfid_user?.rfid_id ?? "-"}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <EmptyState title="Nessuna ricarica importata" message="Il dashboard non ha ancora sessioni nel periodo selezionato." />
              )}
            </Surface>
          </div>

          <div style={{ gridColumn: "span 7" }}>
            <Surface title="Top utenti per energia" subtitle="Classifica essenziale senza grafici pesanti">
              {summaryQuery.data.top_users_by_energy.length ? (
                <div className="list">
                  {summaryQuery.data.top_users_by_energy.map((user, index) => (
                    <div key={`${user.user_id}-${user.rfid_id}`} className="list-item">
                      <div>
                        <div className="list-item__title">
                          #{index + 1} {user.name ?? user.rfid_id}
                        </div>
                        <div className="list-item__meta">{user.session_count} ricariche</div>
                      </div>
                      <StatusBadge
                        tone="neutral"
                        label={`${formatNumber(user.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Nessun utente classificato" message="Non sono presenti ricariche sufficienti per generare la classifica." />
              )}
            </Surface>
          </div>
        </div>
      ) : null}
    </div>
  );
}

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { endpoints } from "../shared/api/endpoints";
import { useQuery } from "../shared/hooks/useQuery";
import { AgentStatusCard } from "../shared/ui/AgentStatusCard";
import {
  DateRange,
  DateRangeControls,
  ErrorState,
  LoadingState,
  PageHead,
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
            <div className="pill">
              Endpoint: <span className="muted">/api/v1/dashboard/summary</span>
            </div>
          </>
        }
      />

      {summaryQuery.loading ? <LoadingState label="Caricamento panoramica…" /> : null}
      {summaryQuery.error ? (
        <ErrorState title="Impossibile caricare la panoramica" message={summaryQuery.error} onRetry={summaryQuery.refetch} />
      ) : null}

      {summaryQuery.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Ricariche totali</div>
            <div className="metric">{summaryQuery.data.total_sessions}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Energia totale (kWh)</div>
            <div className="metric">{formatNumber(summaryQuery.data.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {formatNumber(summaryQuery.data.total_energy_wh)} Wh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Utenti attivi</div>
            <div className="metric">{summaryQuery.data.total_users}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Colonnine attive</div>
            <div className="metric">{summaryQuery.data.total_stations}</div>
          </div>

          <AgentStatusCard status={summaryQuery.data.agent_status} />

          <div className="card" style={{ gridColumn: "span 5" }}>
            <div className="card-title">Ultima ricarica</div>
            {summaryQuery.data.latest_session ? (
              <div style={{ display: "grid", gap: 8 }}>
                <div className="row">
                  <span className="pill is-ok">Importata</span>
                  <span className="pill">
                    Colonnina:{" "}
                    <span className="muted">
                      {summaryQuery.data.latest_session.station?.host ??
                        `#${summaryQuery.data.latest_session.station_id}`}
                    </span>
                  </span>
                  <span className="pill">
                    Tessera:{" "}
                    <span className="muted">
                      {summaryQuery.data.latest_session.rfid_user?.name ??
                        summaryQuery.data.latest_session.rfid_user?.rfid_id ??
                        "-"}
                    </span>
                  </span>
                </div>

                <div className="row">
                  <span className="pill">
                    Fine: <span className="muted">{formatDateTime(summaryQuery.data.latest_session.end_time)}</span>
                  </span>
                  <span className="pill">
                    Energia:{" "}
                    <span className="muted">{formatKwhFromWh(summaryQuery.data.latest_session.energy_wh)} kWh</span>
                  </span>
                  <span className="pill">
                    Durata: <span className="muted">{summaryQuery.data.latest_session.total_minutes} min</span>
                  </span>
                </div>
              </div>
            ) : (
              <div className="muted">Nessuna ricarica importata.</div>
            )}
          </div>

          <div className="card" style={{ gridColumn: "span 7" }}>
            <div className="card-title">Top utenti per energia (kWh)</div>
            {summaryQuery.data.top_users_by_energy.length ? (
              <div style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <BarChart data={summaryQuery.data.top_users_by_energy}>
                    <CartesianGrid stroke="rgba(234, 240, 255, 0.12)" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="rfid_id"
                      tick={{ fill: "rgba(234, 240, 255, 0.75)", fontSize: 12 }}
                      axisLine={{ stroke: "rgba(234, 240, 255, 0.18)" }}
                      tickLine={{ stroke: "rgba(234, 240, 255, 0.18)" }}
                    />
                    <YAxis
                      tick={{ fill: "rgba(234, 240, 255, 0.75)", fontSize: 12 }}
                      axisLine={{ stroke: "rgba(234, 240, 255, 0.18)" }}
                      tickLine={{ stroke: "rgba(234, 240, 255, 0.18)" }}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(17, 26, 46, 0.95)",
                        border: "1px solid rgba(234, 240, 255, 0.15)",
                        borderRadius: 10,
                        color: "rgba(234, 240, 255, 0.9)",
                      }}
                      formatter={(value: any) => [`${formatNumber(Number(value), { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`, "Energia"]}
                      labelFormatter={(label) => `Tessera: ${label}`}
                    />
                    <Bar dataKey="total_energy_kwh" fill="#6aa7ff" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="muted">Nessun utente con ricariche importate.</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

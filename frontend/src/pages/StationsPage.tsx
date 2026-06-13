import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { StationListResponse, StationOccupancyListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatDateTime, formatKwhFromWh } from "../shared/ui";

const DEFAULT_LIMIT = 20;

function occupancyBadge(computed: string | null | undefined) {
  const s = (computed ?? "").toLowerCase();
  if (s === "charging") return { label: "🔴 Charging", tone: "is-danger" as const };
  if (s === "offline") return { label: "⚫ Offline", tone: "is-danger" as const };
  return { label: "🟢 Available", tone: "is-ok" as const };
}

export default function StationsPage() {
  const [offset, setOffset] = useState(0);

  const fetcher = useMemo(
    () => () => endpoints.stations({ limit: DEFAULT_LIMIT, offset }),
    [offset],
  );
  const query = useQuery<StationListResponse>(fetcher);

  const occupancyFetcher = useMemo(() => () => endpoints.stationsOccupancy(), []);
  const occupancyQuery = useQuery<StationOccupancyListResponse>(occupancyFetcher);
  const occupancyById = useMemo(() => {
    const items = occupancyQuery.data?.items ?? [];
    return new Map(items.map((x) => [x.station_id, x]));
  }, [occupancyQuery.data]);

  const total = query.data?.pagination.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + DEFAULT_LIMIT < total;

  return (
    <div>
      <PageHead
        title="Colonnine"
        subtitle="Stato live (occupazione) e dati importati"
        right={
          <div className="pill">
            Endpoint: <span className="muted">/api/v1/stations</span>
          </div>
        }
      />

      {query.loading ? <LoadingState label="Caricamento colonnine…" /> : null}
      {query.error ? (
        <ErrorState title="Impossibile caricare le colonnine" message={query.error} onRetry={query.refetch} />
      ) : null}

      {query.data ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Colonnina</th>
                  <th>Host / IP</th>
                  <th>Ricariche totali</th>
                  <th>Energia totale (kWh)</th>
                  <th>Stato</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{s.name ?? `Colonnina #${s.id}`}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {s.vendor}
                      </div>
                    </td>
                    <td>{s.host}</td>
                    <td>{s.session_count ?? 0}</td>
                    <td>{formatKwhFromWh(s.total_energy_wh)} </td>
                    <td>
                      {(() => {
                        const live = occupancyById.get(s.id);
                        const badge = occupancyBadge(live?.computed_status);
                        return (
                          <div style={{ display: "grid", gap: 6 }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                              <span className={badge.tone ? `pill ${badge.tone}` : "pill"}>{badge.label}</span>
                              <span className="pill">
                                live: <span className="muted">{live ? formatDateTime(live.last_checked_at) : "-"}</span>
                              </span>
                            </div>
                            <div className="muted" style={{ fontSize: 12 }}>
                              import: {formatDateTime(s.last_sync_at)} • sessione attiva: {String(!!s.active_session)} ({s.active_session_source ?? "sconosciuto"})
                            </div>
                            {live?.connector_status ? (
                              <div className="muted" style={{ fontSize: 12 }}>
                                connector_status: {live.connector_status}
                              </div>
                            ) : null}
                          </div>
                        );
                      })()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              className="btn"
              type="button"
              disabled={!canPrev}
              onClick={() => setOffset((o) => Math.max(0, o - DEFAULT_LIMIT))}
            >
              Precedente
            </button>
            <div className="muted">
              {total ? `${offset + 1}-${Math.min(offset + DEFAULT_LIMIT, total)} di ${total}` : "0"}
            </div>
            <button className="btn" type="button" disabled={!canNext} onClick={() => setOffset((o) => o + DEFAULT_LIMIT)}>
              Successivo
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

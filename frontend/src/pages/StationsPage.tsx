import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { StationListResponse, StationOccupancyListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatDateTime, formatKwhFromWh } from "../shared/ui";

const DEFAULT_LIMIT = 20;

function normalizeStatus(value: string | null | undefined) {
  const s = (value ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return "busy";
  if (s === "free" || s === "available") return "free";
  if (s === "unavailable" || s === "offline" || s === "faulted" || s === "unknown" || s === "unreachable" || s === "degraded") {
    return "unavailable";
  }
  return null;
}

function occupancyBadge(computed: string | null | undefined) {
  const s = (computed ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return { label: "🔴 Busy", tone: "is-danger" as const };
  if (s === "free" || s === "available") return { label: "🟢 Free", tone: "is-ok" as const };
  return { label: "⚫ Unavailable", tone: "is-danger" as const };
}

function resolveDisplayedStatus(
  station: { status: string | null; status_is_fresh: boolean },
  live?: { computed_status: string; source: string } | null,
) {
  const known = normalizeStatus(station.status);
  const liveStatus = normalizeStatus(live?.computed_status);
  if (live?.source === "agent" && liveStatus) return liveStatus;
  if (station.status_is_fresh && known && liveStatus === "unavailable") return known;
  return liveStatus ?? known;
}

function resolveDisplayedCheckedAt(
  station: { status: string | null; status_is_fresh: boolean; last_seen_at: string | null; last_poll_at: string | null; last_sync_at: string | null },
  live?: { computed_status: string; source: string; last_checked_at: string } | null,
) {
  if (live?.source === "agent") return live.last_checked_at;
  if (station.status_is_fresh && normalizeStatus(station.status) && normalizeStatus(live?.computed_status) === "unavailable") {
    return station.last_seen_at ?? station.last_poll_at ?? station.last_sync_at;
  }
  return live?.last_checked_at ?? station.last_seen_at ?? station.last_poll_at ?? station.last_sync_at;
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
                        const displayStatus = resolveDisplayedStatus(s, live);
                        const checkedAt = resolveDisplayedCheckedAt(s, live);
                        const badge = occupancyBadge(displayStatus ?? "offline");
                        return (
                          <div style={{ display: "grid", gap: 6 }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                              <span className={badge.tone ? `pill ${badge.tone}` : "pill"}>{badge.label}</span>
                              <span className="pill">
                                Last status check:{" "}
                                <span className="muted">{formatDateTime(checkedAt)}</span>
                              </span>
                            </div>
                            <div className="muted" style={{ fontSize: 12 }}>
                              Last synchronization: {formatDateTime(s.last_sync_at)} • sessione attiva:{" "}
                              {String(!!s.active_session)} ({s.active_session_source ?? "sconosciuto"})
                            </div>
                            <div className="muted" style={{ fontSize: 12 }}>
                              Last charging session: {formatDateTime(s.latest_session?.end_time)}
                            </div>
                            {(live?.connector_status ?? s.connector_status) ? (
                              <div className="muted" style={{ fontSize: 12 }}>
                                connector_status: {live?.connector_status ?? s.connector_status}
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

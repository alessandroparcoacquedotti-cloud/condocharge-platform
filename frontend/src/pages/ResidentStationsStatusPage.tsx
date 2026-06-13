import { useMemo } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentStationOccupancyListResponse, ResidentStationStatusListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatAgeFromNow, formatDateTime, formatKwhFromWh } from "../shared/ui";

const REFRESH_MS = 10000;
const STALE_AFTER_MS = 30000;

function occupancyBadge(computed: string | null | undefined, opts: { checking: boolean }) {
  const s = (computed ?? "").toLowerCase();
  if (s === "charging") return { label: "🔴 CHARGING", tone: "is-danger" as const };
  if (s === "offline") return { label: "⚫ UNAVAILABLE", tone: "is-danger" as const };
  if (opts.checking) return { label: "🟡 CHECKING STATUS", tone: "" as const };
  return { label: "🟢 FREE", tone: "is-ok" as const };
}

export default function ResidentStationsStatusPage() {
  const fetcher = useMemo(() => () => endpoints.residentStationsStatus(), []);
  const query = useQuery<ResidentStationStatusListResponse>(fetcher);
  const occupancyFetcher = useMemo(() => () => endpoints.residentStationsOccupancy(), []);
  const occupancyQuery = useQuery<ResidentStationOccupancyListResponse>(occupancyFetcher, { refetchIntervalMs: REFRESH_MS });
  const occupancyById = useMemo(() => {
    const items = occupancyQuery.data?.items ?? [];
    return new Map(items.map((x) => [x.station_id, x]));
  }, [occupancyQuery.data]);
  const now = new Date();

  return (
    <div>
      <PageHead
        title="Stato colonnine"
        subtitle="Disponibilità live e ultima ricarica registrata"
      />

      {query.loading ? <LoadingState label="Caricamento colonnine…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare lo stato colonnine" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          {query.data.items.map((s) => {
            const live = occupancyById.get(s.id);
            const checkedAtMs = live?.last_checked_at ? new Date(live.last_checked_at).getTime() : null;
            const ageMs = checkedAtMs != null && !Number.isNaN(checkedAtMs) ? Math.max(0, now.getTime() - checkedAtMs) : null;
            const isStale = ageMs != null ? ageMs > STALE_AFTER_MS : true;
            const waitingForLive = occupancyQuery.loading || occupancyQuery.refreshing;
            const checking = !live || isStale || (waitingForLive && (live?.computed_status ?? "").toLowerCase() === "available");
            const badge = occupancyBadge(live?.computed_status ?? s.known_status ?? "offline", { checking });
            return (
              <div key={s.id} className="card" style={{ gridColumn: "span 6" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: 16 }}>{s.name ?? `Stazione #${s.id}`}</div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                      Ultimo aggiornamento dati: {formatDateTime(s.last_sync_at)}
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                      {live ? `${formatAgeFromNow(live.last_checked_at, now)} (${formatDateTime(live.last_checked_at)})` : "🟡 CHECKING STATUS…"}
                    </div>
                  </div>
                  <span className={badge.tone ? `pill ${badge.tone}` : "pill"}>{badge.label}</span>
                </div>

                <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
                  <div className="pill" style={{ justifyContent: "space-between" }}>
                    <span>Ultima ricarica registrata</span>
                    <span className="muted">
                      {s.last_charge ? formatDateTime(s.last_charge.end_time) : "-"}
                    </span>
                  </div>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <span className="pill">
                      Energia: <span className="muted">{s.last_charge ? `${formatKwhFromWh(s.last_charge.energy_wh)} kWh` : "-"}</span>
                    </span>
                    <span className="pill">
                      Durata: <span className="muted">{s.last_charge ? `${s.last_charge.total_minutes} min` : "-"}</span>
                    </span>
                  </div>
                </div>
              </div>
            );
          })}

          {!query.data.items.length ? (
            <div className="card" style={{ gridColumn: "span 12" }}>
              <div className="muted">Nessuna colonnina disponibile per questo condominio.</div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

import { useMemo } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentStationOccupancyListResponse, ResidentStationStatusListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHead,
  StatusBadge,
  Surface,
  formatAgeFromNow,
  formatDateTime,
  formatKwhFromWh,
} from "../shared/ui";

const REFRESH_MS = 10000;
const STALE_AFTER_MS = 30000;

function normalizeStatus(value: string | null | undefined) {
  const s = (value ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return "busy";
  if (s === "free" || s === "available") return "free";
  if (s === "unavailable" || s === "offline" || s === "faulted" || s === "unknown" || s === "unreachable" || s === "degraded") {
    return "unavailable";
  }
  return null;
}

function occupancyBadge(computed: string | null | undefined, opts: { checking: boolean }) {
  const s = (computed ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return { label: "In uso", tone: "is-danger" as const };
  if (s === "unavailable" || s === "offline" || s === "faulted" || s === "unknown" || s === "unreachable" || s === "degraded") {
    return { label: "Non disponibile", tone: "is-danger" as const };
  }
  if (opts.checking) return { label: "Verifica in corso", tone: "is-warn" as const };
  return { label: "Libera", tone: "is-ok" as const };
}

function occupancyLabel(computed: string | null | undefined, opts: { checking: boolean }) {
  const s = (computed ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return "In uso";
  if (s === "unavailable" || s === "offline" || s === "faulted" || s === "unknown" || s === "unreachable" || s === "degraded") {
    return "Non disponibile";
  }
  if (opts.checking) return "Verifica in corso";
  return "Libera";
}

function resolveDisplayedStatus(
  knownStatus: string | null | undefined,
  statusIsFresh: boolean,
  live?: { computed_status: string; source: string } | null,
) {
  const known = normalizeStatus(knownStatus);
  const liveStatus = normalizeStatus(live?.computed_status);
  if (live?.source === "agent" && liveStatus) return liveStatus;
  if (statusIsFresh && known && liveStatus === "unavailable") return known;
  return liveStatus ?? known;
}

function resolveDisplayedCheckedAt(
  station: {
    status_is_fresh: boolean;
    known_status: string | null;
    last_seen_at: string | null;
    last_poll_at: string | null;
    last_sync_at: string | null;
  },
  live?: { computed_status: string; source: string; last_checked_at: string } | null,
) {
  if (live?.source === "agent") return live.last_checked_at;
  if (station.status_is_fresh && normalizeStatus(station.known_status) && normalizeStatus(live?.computed_status) === "unavailable") {
    return station.last_seen_at ?? station.last_poll_at ?? station.last_sync_at;
  }
  return live?.last_checked_at ?? station.last_seen_at ?? station.last_poll_at ?? station.last_sync_at;
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
  const stats = useMemo(() => {
    const items = query.data?.items ?? [];
    let free = 0;
    let busy = 0;
    let unavailable = 0;
    for (const station of items) {
      const live = occupancyById.get(station.id);
      const displayStatus = resolveDisplayedStatus(station.known_status, station.status_is_fresh, live);
      if (displayStatus === "free") free += 1;
      else if (displayStatus === "busy") busy += 1;
      else unavailable += 1;
    }
    return { total: items.length, free, busy, unavailable };
  }, [occupancyById, query.data]);

  return (
    <div>
      <PageHead title="Stato colonnine" subtitle="Disponibilita in tempo reale e ultimo aggiornamento" />

      {query.loading ? <LoadingState label="Caricamento colonnine…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare lo stato colonnine" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          <div style={{ gridColumn: "span 12", display: "flex", justifyContent: "flex-end" }}>
            <button className="btn btn--primary touch-safe" type="button" onClick={() => occupancyQuery.refetch()}>
              Aggiorna
            </button>
          </div>

          {query.data.items.map((s) => {
            const live = occupancyById.get(s.id);
            const displayStatus = resolveDisplayedStatus(s.known_status, s.status_is_fresh, live);
            const checkedAt = resolveDisplayedCheckedAt(s, live);
            const checkedAtMs = checkedAt ? new Date(checkedAt).getTime() : null;
            const ageMs = checkedAtMs != null && !Number.isNaN(checkedAtMs) ? Math.max(0, now.getTime() - checkedAtMs) : null;
            const isStale = ageMs != null ? ageMs > STALE_AFTER_MS : true;
            const waitingForLive = occupancyQuery.loading || occupancyQuery.refreshing;
            const usingFreshKnownStatus =
              s.status_is_fresh && normalizeStatus(s.known_status) != null && normalizeStatus(live?.computed_status) === "unavailable" && live?.source !== "agent";
            const checking = !displayStatus || (!usingFreshKnownStatus && (!live || isStale || (waitingForLive && displayStatus === "free")));
            const badge = occupancyBadge(displayStatus ?? "offline", { checking });
            return (
              <div key={s.id} className="card station-card" style={{ gridColumn: "span 6" }}>
                <div className="station-card__head">
                  <div>
                    <h2 className="station-card__title">{s.name ?? `Colonnina #${s.id}`}</h2>
                    <div className="station-card__subtitle">Ultimo aggiornamento dati: {formatDateTime(s.last_sync_at)}</div>
                    <div className="station-card__subtitle">
                      {checkedAt ? `${formatAgeFromNow(checkedAt, now)} (${formatDateTime(checkedAt)})` : "Verifica in corso"}
                    </div>
                  </div>
                  <StatusBadge
                    tone={badge.tone === "is-ok" ? "ok" : badge.tone === "is-danger" ? "danger" : badge.tone === "is-warn" ? "warn" : "neutral"}
                    label={badge.label}
                  />
                </div>

                <div className="detail-grid">
                  <div className="detail-card kv">
                    <div className="kv__label">Ultima ricarica</div>
                    <div className="kv__value">{s.last_charge ? formatDateTime(s.last_charge.end_time) : "-"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Energia</div>
                    <div className="kv__value">{s.last_charge ? `${formatKwhFromWh(s.last_charge.energy_wh)} kWh` : "-"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Durata</div>
                    <div className="kv__value">{s.last_charge ? `${s.last_charge.total_minutes} min` : "-"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Stato live</div>
                    <div className="kv__value">{occupancyLabel(displayStatus ?? "offline", { checking })}</div>
                  </div>
                </div>

                <div className="row">
                  <StatusBadge tone="neutral" label={checkedAt ? formatDateTime(checkedAt) : "Verifica in corso"} />
                  <StatusBadge tone={isStale ? "warn" : "ok"} label={isStale ? "Ultimo aggiornamento non recente" : "Aggiornato"} />
                </div>
              </div>
            );
          })}

          {!query.data.items.length ? (
            <div style={{ gridColumn: "span 12" }}>
              <EmptyState
                title="Nessuna colonnina disponibile"
                message="Quando una stazione verra configurata qui comparira il suo stato in tempo reale."
              />
            </div>
          ) : null}

          <div style={{ gridColumn: "span 12" }}>
            <Surface title="Riepilogo" subtitle="Numero di colonnine per stato (solo dopo la lista)">
              <div className="row">
                <StatusBadge tone="ok" label={`Libere: ${stats.free}`} />
                <StatusBadge tone="danger" label={`In uso: ${stats.busy}`} />
                <StatusBadge tone="warn" label={`Non disponibili: ${stats.unavailable}`} />
              </div>
            </Surface>
          </div>
        </div>
      ) : null}
    </div>
  );
}

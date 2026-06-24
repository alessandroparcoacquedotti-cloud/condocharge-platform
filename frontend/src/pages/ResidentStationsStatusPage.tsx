import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

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
  WallboxIcon,
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

function occupancyLabel(computed: string | null | undefined, opts: { checking: boolean }) {
  const s = (computed ?? "").toLowerCase();
  if (s === "busy" || s === "charging" || s === "occupied") return "In uso";
  if (s === "unavailable" || s === "offline" || s === "faulted" || s === "unknown" || s === "unreachable" || s === "degraded") {
    return "Non disponibile";
  }
  if (opts.checking) return "Verifica in corso";
  return "Libera";
}

function badgeToneFromLabel(label: string) {
  if (label === "Libera") return "ok" as const;
  if (label === "In uso" || label === "Non disponibile") return "danger" as const;
  if (label === "Verifica in corso") return "warn" as const;
  return "neutral" as const;
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
  const navigate = useNavigate();
  const { stationId } = useParams();
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
  const selectedStation = useMemo(() => {
    if (!stationId || !query.data) return null;
    return query.data.items.find((item) => String(item.id) === stationId) ?? null;
  }, [query.data, stationId]);

  const selectedLive = selectedStation ? occupancyById.get(selectedStation.id) : undefined;
  const selectedDisplayStatus = selectedStation
    ? resolveDisplayedStatus(selectedStation.known_status, selectedStation.status_is_fresh, selectedLive)
    : null;
  const selectedCheckedAt = selectedStation ? resolveDisplayedCheckedAt(selectedStation, selectedLive) : null;
  const selectedAgeMs =
    selectedCheckedAt != null ? Math.max(0, now.getTime() - new Date(selectedCheckedAt).getTime()) : null;
  const selectedIsStale = selectedAgeMs != null ? selectedAgeMs > STALE_AFTER_MS : true;
  const selectedUsingFreshKnownStatus =
    selectedStation != null &&
    selectedStation.status_is_fresh &&
    normalizeStatus(selectedStation.known_status) != null &&
    normalizeStatus(selectedLive?.computed_status) === "unavailable" &&
    selectedLive?.source !== "agent";
  const selectedChecking =
    selectedStation != null &&
    (!selectedDisplayStatus ||
      (!selectedUsingFreshKnownStatus &&
        (!selectedLive || selectedIsStale || ((occupancyQuery.loading || occupancyQuery.refreshing) && selectedDisplayStatus === "free"))));
  const selectedStatusLabel = selectedStation
    ? occupancyLabel(selectedDisplayStatus ?? "offline", { checking: selectedChecking })
    : null;

  if (stationId) {
    return (
      <div>
        <PageHead
          title={selectedStation?.name ?? "Dettaglio colonnina"}
          subtitle="Dettagli, ultima sessione e stato aggiornato"
          right={
            <button className="btn btn--secondary touch-safe" type="button" onClick={() => navigate("/resident/stato-colonnine")}>
              Torna alle colonnine
            </button>
          }
        />

        {query.loading ? <LoadingState label="Caricamento colonnina..." /> : null}
        {query.error ? <ErrorState title="Impossibile caricare la colonnina" message={query.error} onRetry={query.refetch} /> : null}

        {query.data && !selectedStation ? (
          <EmptyState title="Colonnina non trovata" message="Questa colonnina non e disponibile per il tuo condominio." />
        ) : null}

        {selectedStation ? (
          <div className="grid">
            <div style={{ gridColumn: "span 12" }}>
              <Surface
                title={selectedStation.name ?? `Colonnina #${selectedStation.id}`}
                subtitle="Panoramica rapida"
                aside={selectedStatusLabel ? <StatusBadge tone={badgeToneFromLabel(selectedStatusLabel)} label={selectedStatusLabel} /> : null}
                className="surface--accent"
              >
                <div className="detail-grid">
                  <div className="detail-card kv">
                    <div className="kv__label">Ultimo aggiornamento</div>
                    <div className="kv__value">{selectedCheckedAt ? formatAgeFromNow(selectedCheckedAt, now) : "Verifica in corso"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Controllo live</div>
                    <div className="kv__value">{formatDateTime(selectedCheckedAt)}</div>
                  </div>
                </div>
              </Surface>
            </div>

            <div style={{ gridColumn: "span 12" }}>
              <Surface title="Ultima sessione" subtitle="Dettagli dell'ultima ricarica registrata">
                {selectedStation.last_charge ? (
                  <div className="detail-grid">
                    <div className="detail-card kv">
                      <div className="kv__label">Fine sessione</div>
                      <div className="kv__value">{formatDateTime(selectedStation.last_charge.end_time)}</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Energia</div>
                      <div className="kv__value">{formatKwhFromWh(selectedStation.last_charge.energy_wh)} kWh</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Durata</div>
                      <div className="kv__value">{selectedStation.last_charge.total_minutes} min</div>
                    </div>
                  </div>
                ) : (
                  <EmptyState title="Nessuna sessione registrata" message="Non ci sono ancora dati di ricarica per questa colonnina." />
                )}
              </Surface>
            </div>

            <div style={{ gridColumn: "span 12" }}>
              <Surface title="Dettagli tecnici" subtitle="Informazioni utili se serve capire lo stato della colonnina">
                <div className="detail-grid">
                  <div className="detail-card kv">
                    <div className="kv__label">Ultima sincronizzazione</div>
                    <div className="kv__value">{formatDateTime(selectedStation.last_sync_at)}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Ultimo seen</div>
                    <div className="kv__value">{formatDateTime(selectedStation.last_seen_at)}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Ultimo poll</div>
                    <div className="kv__value">{formatDateTime(selectedStation.last_poll_at)}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Sorgente stato</div>
                    <div className="kv__value">{selectedLive?.source ?? selectedStation.status_source ?? "-"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Connector status</div>
                    <div className="kv__value">{selectedStation.connector_status ?? "-"}</div>
                  </div>
                  <div className="detail-card kv">
                    <div className="kv__label">Charging state</div>
                    <div className="kv__value">{selectedStation.charging_state ?? "-"}</div>
                  </div>
                </div>
              </Surface>
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div>
      <PageHead title="Condo Charge" subtitle="Disponibilità in tempo reale" />

      {query.loading ? <LoadingState label="Caricamento colonnine…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare lo stato colonnine" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          <div style={{ gridColumn: "span 12" }}>
            <div className="device-tile-grid">
              {query.data.items.map((s) => {
                const live = occupancyById.get(s.id);
                const displayStatus = resolveDisplayedStatus(s.known_status, s.status_is_fresh, live);
                const checkedAt = resolveDisplayedCheckedAt(s, live);
                const checkedAtMs = checkedAt ? new Date(checkedAt).getTime() : null;
                const ageMs = checkedAtMs != null && !Number.isNaN(checkedAtMs) ? Math.max(0, now.getTime() - checkedAtMs) : null;
                const isStale = ageMs != null ? ageMs > STALE_AFTER_MS : true;
                const waitingForLive = occupancyQuery.loading || occupancyQuery.refreshing;
                const usingFreshKnownStatus =
                  s.status_is_fresh &&
                  normalizeStatus(s.known_status) != null &&
                  normalizeStatus(live?.computed_status) === "unavailable" &&
                  live?.source !== "agent";
                const checking =
                  !displayStatus ||
                  (!usingFreshKnownStatus && (!live || isStale || (waitingForLive && displayStatus === "free")));
                const statusLabel = occupancyLabel(displayStatus ?? "offline", { checking });
                const statusTone = badgeToneFromLabel(statusLabel);
                return (
                  <div
                    key={s.id}
                    className={`device-tile device-tile--${statusTone}`}       
                  >
                    <WallboxIcon className="device-tile__icon" />
                    <div className={`device-tile__status device-tile__status--${statusTone}`}>{statusLabel}</div>
                    <div className="device-tile__title">{s.name ?? `Colonnina ${s.id}`}</div>
                    <div className="device-tile__meta">
                      {checkedAt ? formatAgeFromNow(checkedAt, now) : "Verifica in corso"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {!query.data.items.length ? (
            <div style={{ gridColumn: "span 12" }}>
              <EmptyState
                title="Nessuna colonnina disponibile"
                message="Quando una stazione verra configurata qui comparira il suo stato in tempo reale."
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

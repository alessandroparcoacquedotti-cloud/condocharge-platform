import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentSessionListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { DateRange, DateRangeControls, ErrorState, LoadingState, PageHead, buildPresetRange, formatDateTime, formatKwhFromWh, toApiRange } from "../shared/ui";

const DEFAULT_LIMIT = 20;

function durationLabel(totalMinutes: number | null | undefined) {
  if (totalMinutes == null) return "-";
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}h ${m}m`;
}

export default function ResidentSessionsPage() {
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last30", fromDate: null, toDate: null }));
  const [offset, setOffset] = useState(0);

  const fetcher = useMemo(
    () => () => endpoints.residentSessions({ limit: DEFAULT_LIMIT, offset, ...toApiRange(range) }),
    [offset, range],
  );
  const query = useQuery<ResidentSessionListResponse>(fetcher);

  const total = query.data?.pagination.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + DEFAULT_LIMIT < total;

  return (
    <div>
      <PageHead
        title="Le mie ricariche"
        subtitle="Elenco delle ricariche registrate per le tue tessere"
        right={
          <>
            <DateRangeControls
              range={range}
              onChange={(next) => {
                setOffset(0);
                if (next.preset !== "custom") {
                  const preset = buildPresetRange(next.preset);
                  setRange({ preset: next.preset, fromDate: preset.fromDate, toDate: preset.toDate });
                } else {
                  setRange(next);
                }
              }}
            />
            <button className="btn" type="button" onClick={() => query.refetch()}>
              Aggiorna
            </button>
          </>
        }
      />

      {query.loading ? <LoadingState label="Caricamento ricariche…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare le ricariche" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          {query.data.items.map((s) => (
            <div key={s.id} className="card" style={{ gridColumn: "span 6" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                <div style={{ fontWeight: 800 }}>
                  {s.station?.name ?? "Colonnina"} <span className="muted">{s.station?.name ? "" : `#${s.station_id}`}</span>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  Fine: {formatDateTime(s.end_time)}
                </div>
              </div>

              <div className="row" style={{ marginTop: 10, justifyContent: "space-between" }}>
                <span className="pill">
                  Energia: <span className="muted">{formatKwhFromWh(s.energy_wh)} kWh</span>
                </span>
                <span className="pill">
                  Durata: <span className="muted">{durationLabel(s.total_minutes)}</span>
                </span>
              </div>

              <div className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Inizio: {formatDateTime(s.start_time)}
              </div>
            </div>
          ))}

          {!query.data.items.length ? (
            <div className="card" style={{ gridColumn: "span 12" }}>
              <div className="muted">Nessuna ricarica nel periodo selezionato.</div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="pagination">
        <button className="btn" type="button" disabled={!canPrev} onClick={() => setOffset((o) => Math.max(0, o - DEFAULT_LIMIT))}>
          Precedente
        </button>
        <div className="muted">{total ? `${offset + 1}-${Math.min(offset + DEFAULT_LIMIT, total)} di ${total}` : "0"}</div>
        <button className="btn" type="button" disabled={!canNext} onClick={() => setOffset((o) => o + DEFAULT_LIMIT)}>
          Successivo
        </button>
      </div>
    </div>
  );
}

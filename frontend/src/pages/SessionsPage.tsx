import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { SessionListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { DateRange, DateRangeControls, ErrorState, LoadingState, PageHead, buildPresetRange, formatDateTime, formatKwhFromWh, toApiRange } from "../shared/ui";

const DEFAULT_LIMIT = 25;

function durationLabel(totalMinutes: number | null | undefined) {
  if (totalMinutes == null) return "-";
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}h ${m}m`;
}

export default function SessionsPage() {
  const [offset, setOffset] = useState(0);
  const [rfidId, setRfidId] = useState("");
  const [stationId, setStationId] = useState("");
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last7", fromDate: null, toDate: null }));

  const fetcher = useMemo(
    () => () =>
      endpoints.sessions({
        limit: DEFAULT_LIMIT,
        offset,
        ...toApiRange(range),
        rfid_id: rfidId.trim() ? rfidId.trim() : undefined,
        station_id: stationId.trim() ? Number(stationId.trim()) : undefined,
      }),
    [offset, rfidId, stationId, range],
  );
  const query = useQuery<SessionListResponse>(fetcher);

  const total = query.data?.pagination.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + DEFAULT_LIMIT < total;

  return (
    <div>
      <PageHead
        title="Ricariche"
        subtitle="Ricariche importate (paginazione)"
        right={
          <>
            <div className="pill">
              Endpoint: <span className="muted">/api/v1/sessions</span>
            </div>
            <button className="btn" type="button" onClick={() => query.refetch()}>
              Aggiorna
            </button>
          </>
        }
      />

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row">
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
          <div className="pill">
            Tessera:&nbsp;
            <input
              value={rfidId}
              onChange={(e) => {
                setOffset(0);
                setRfidId(e.target.value);
              }}
              placeholder="es. 1234"
              style={{
                background: "transparent",
                border: "none",
                outline: "none",
                color: "inherit",
                width: 140,
              }}
            />
          </div>
          <div className="pill">
            Colonnina ID:&nbsp;
            <input
              value={stationId}
              onChange={(e) => {
                setOffset(0);
                setStationId(e.target.value);
              }}
              placeholder="es. 1"
              style={{
                background: "transparent",
                border: "none",
                outline: "none",
                color: "inherit",
                width: 90,
              }}
            />
          </div>
          {(rfidId || stationId) && (
            <button
              className="btn"
              type="button"
              onClick={() => {
                setOffset(0);
                setRfidId("");
                setStationId("");
              }}
            >
              Pulisci filtri
            </button>
          )}
        </div>
      </div>

      {query.loading ? <LoadingState label="Caricamento ricariche…" /> : null}
      {query.error ? (
        <ErrorState title="Impossibile caricare le ricariche" message={query.error} onRetry={query.refetch} />
      ) : null}

      {query.data ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Colonnina</th>
                  <th>Tessera</th>
                  <th>Inizio</th>
                  <th>Fine</th>
                  <th>Energia (kWh)</th>
                  <th>Durata</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{s.station?.host ?? `#${s.station_id}`}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {s.station?.name ?? ""}
                      </div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 700 }}>{s.rfid_user?.name ?? "-"}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {s.rfid_user?.rfid_id ?? "-"}
                      </div>
                    </td>
                    <td>{formatDateTime(s.start_time)}</td>
                    <td>{formatDateTime(s.end_time)}</td>
                    <td>{formatKwhFromWh(s.energy_wh)}</td>
                    <td>{durationLabel(s.total_minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button className="btn" type="button" disabled={!canPrev} onClick={() => setOffset((o) => Math.max(0, o - DEFAULT_LIMIT))}>
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

import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { AdminCostReportResponse, AdminResidentRow, AdminRfidUserRow, CostByResidentRow } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import {
  DateRange,
  DateRangeControls,
  ErrorState,
  LoadingState,
  PageHead,
  buildPresetRange,
  formatCurrencyEur,
  formatNumber,
  toApiRange,
} from "../shared/ui";

type SortKey = "resident" | "sessions_count" | "energy_kwh" | "estimated_cost_eur" | "rfid_count";
type SortDir = "asc" | "desc";

function sortRows(rows: CostByResidentRow[], key: SortKey, dir: SortDir) {
  const factor = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[key] as any;
    const bv = b[key] as any;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * factor;
    return String(av).localeCompare(String(bv)) * factor;
  });
}

export default function AdminCostReportPage() {
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last30", fromDate: null, toDate: null }));
  const [sortKey, setSortKey] = useState<SortKey>("estimated_cost_eur");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [exporting, setExporting] = useState(false);
  const [residentId, setResidentId] = useState("");
  const [rfidUserId, setRfidUserId] = useState("");

  const residentsFetcher = useMemo(() => () => endpoints.adminResidents(), []);
  const rfidUsersFetcher = useMemo(() => () => endpoints.adminRfidUsers(), []);
  const residentsQuery = useQuery<AdminResidentRow[]>(residentsFetcher);
  const rfidUsersQuery = useQuery<AdminRfidUserRow[]>(rfidUsersFetcher);

  const reportParams = useMemo(
    () => ({
      ...toApiRange(range),
      resident_id: residentId ? Number(residentId) : undefined,
      rfid_user_id: rfidUserId ? Number(rfidUserId) : undefined,
    }),
    [range, residentId, rfidUserId],
  );

  const fetcher = useMemo(() => () => endpoints.adminCostReport(reportParams), [reportParams]);
  const query = useQuery<AdminCostReportResponse>(fetcher);

  const rows = query.data ? sortRows(query.data.by_resident, sortKey, sortDir) : [];
  const residentOptions = (residentsQuery.data ?? []).filter((row) => row.role === "resident");
  const rfidOptions = (rfidUsersQuery.data ?? []).filter((row) => (!residentId ? true : String(row.app_user_id ?? "") === residentId));

  function toggleSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDir(nextKey === "resident" ? "asc" : "desc");
  }

  async function downloadCsv() {
    setExporting(true);
    try {
      const res = await endpoints.adminCostReportCsv(reportParams);
      if (!res.ok) {
        throw new Error(`Esportazione non riuscita (${res.status})`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "condocharge_cost_report.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div>
      <PageHead
        title="Costi"
        subtitle="Totali consumi condominiali e costi stimati"
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
            <button className="btn" type="button" disabled={exporting} onClick={downloadCsv}>
              {exporting ? "Esportazione…" : "Esporta CSV"}
            </button>
          </>
        }
      />

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row">
          <div className="pill">
            Residente:&nbsp;
            <select
              value={residentId}
              onChange={(e) => {
                setResidentId(e.target.value);
                setRfidUserId("");
              }}
              style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}
            >
              <option value="">Tutti</option>
              {residentOptions.map((resident) => (
                <option key={resident.app_user_id} value={resident.app_user_id}>
                  {resident.username}
                </option>
              ))}
            </select>
          </div>
          <div className="pill">
            Tessera:&nbsp;
            <select
              value={rfidUserId}
              onChange={(e) => setRfidUserId(e.target.value)}
              style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}
            >
              <option value="">Tutte</option>
              {rfidOptions.map((rfid) => (
                <option key={rfid.id} value={rfid.id}>
                  {rfid.rfid_id}
                </option>
              ))}
            </select>
          </div>
          {(residentId || rfidUserId) && (
            <button
              className="btn"
              type="button"
              onClick={() => {
                setResidentId("");
                setRfidUserId("");
              }}
            >
              Pulisci filtri
            </button>
          )}
        </div>
      </div>

      {query.loading ? <LoadingState label="Caricamento costi…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare i costi" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Energia totale (kWh)</div>
            <div className="metric">{formatNumber(query.data.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {formatNumber(query.data.total_energy_wh)} Wh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Costo totale stimato</div>
            <div className="metric">{formatCurrencyEur(query.data.total_estimated_cost_eur)}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Prezzo energia: {formatCurrencyEur(query.data.energy_price_eur_per_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}/kWh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Ricariche totali</div>
            <div className="metric">{query.data.total_sessions}</div>
          </div>

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Per residente</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ cursor: "pointer" }} onClick={() => toggleSort("resident")}>
                      Residente
                    </th>
                    <th style={{ cursor: "pointer" }} onClick={() => toggleSort("sessions_count")}>
                      Ricariche
                    </th>
                    <th style={{ cursor: "pointer" }} onClick={() => toggleSort("energy_kwh")}>
                      Energia (kWh)
                    </th>
                    <th style={{ cursor: "pointer" }} onClick={() => toggleSort("estimated_cost_eur")}>
                      Costo stimato
                    </th>
                    <th style={{ cursor: "pointer" }} onClick={() => toggleSort("rfid_count")}>
                      Tessere RFID
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.app_user_id ?? r.resident}>
                      <td style={{ fontWeight: 700 }}>{r.resident}</td>
                      <td>{r.sessions_count}</td>
                      <td>{formatNumber(r.energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                      <td>{formatCurrencyEur(r.estimated_cost_eur)}</td>
                      <td>{r.rfid_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

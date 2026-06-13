import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentSummaryResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import {
  DateRange,
  DateRangeControls,
  ErrorState,
  LoadingState,
  PageHead,
  buildPresetRange,
  formatCurrencyEur,
  formatDateTime,
  formatKwhFromWh,
  formatNumber,
  toApiRange,
} from "../shared/ui";

export default function ResidentDashboardPage() {
  const [range, setRange] = useState<DateRange>(() => ({ preset: "last7", fromDate: null, toDate: null }));

  const summaryFetcher = useMemo(() => () => endpoints.residentSummary(toApiRange(range)), [range]);
  const summaryQuery = useQuery<ResidentSummaryResponse>(summaryFetcher);

  return (
    <div>
      <PageHead
        title="I miei consumi"
        subtitle="Consumi e costi stimati nel periodo selezionato"
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
            <button
              className="btn"
              type="button"
              onClick={() => {
                summaryQuery.refetch();
              }}
            >
              Aggiorna
            </button>
          </>
        }
      />

      {summaryQuery.loading && <LoadingState label="Caricamento consumi…" />}
      {summaryQuery.error ? (
        <ErrorState title="Impossibile caricare i consumi" message={summaryQuery.error} onRetry={summaryQuery.refetch} />
      ) : null}

      {summaryQuery.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Ricariche totali</div>
            <div className="metric">{summaryQuery.data.total_sessions}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Energia totale (kWh)</div>
            <div className="metric">
              {formatNumber(summaryQuery.data.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {formatNumber(summaryQuery.data.total_energy_wh)} Wh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Spesa stimata</div>
            <div className="metric">{formatCurrencyEur(summaryQuery.data.estimated_cost_eur)}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Prezzo energia: {formatCurrencyEur(summaryQuery.data.energy_price_eur_per_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}/kWh
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Spesa annua stimata</div>
            <div className="metric">{formatCurrencyEur(summaryQuery.data.estimated_annual_cost_eur)}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Basata sul periodo selezionato
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Ultima ricarica registrata</div>
            <div className="metric" style={{ fontSize: 18 }}>
              {formatDateTime(summaryQuery.data.latest_session?.end_time ?? null)}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {summaryQuery.data.latest_session
                ? `${formatKwhFromWh(summaryQuery.data.latest_session.energy_wh)} kWh`
                : "Nessuna ricarica registrata nel periodo selezionato"}
            </div>
          </div>

          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Tessere collegate</div>
            {summaryQuery.data.cards.length ? (
              <div style={{ display: "grid", gap: 8 }}>
                {summaryQuery.data.cards.map((c) => (
                  <div key={c.id} className="pill" style={{ justifyContent: "space-between" }}>
                    <span>{c.name ?? "Tessera senza nome"}</span>
                    <span className="muted">{c.rfid_id}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted">Nessuna tessera collegata al tuo account.</div>
            )}
          </div>
          <div className="card" style={{ gridColumn: "span 6" }}>
            <div className="card-title">Andamento mensile</div>
            {summaryQuery.data.monthly_breakdown.length ? (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <BarChart data={summaryQuery.data.monthly_breakdown}>
                    <CartesianGrid stroke="rgba(234, 240, 255, 0.12)" strokeDasharray="3 3" />
                    <XAxis dataKey="month" tick={{ fill: "rgba(234, 240, 255, 0.75)", fontSize: 12 }} axisLine={{ stroke: "rgba(234, 240, 255, 0.18)" }} tickLine={{ stroke: "rgba(234, 240, 255, 0.18)" }} />
                    <YAxis tick={{ fill: "rgba(234, 240, 255, 0.75)", fontSize: 12 }} axisLine={{ stroke: "rgba(234, 240, 255, 0.18)" }} tickLine={{ stroke: "rgba(234, 240, 255, 0.18)" }} />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(17, 26, 46, 0.95)",
                        border: "1px solid rgba(234, 240, 255, 0.15)",
                        borderRadius: 10,
                        color: "rgba(234, 240, 255, 0.9)",
                      }}
                      formatter={(value: any) => [`${formatNumber(Number(value), { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`, "Energia"]}
                    />
                    <Bar dataKey="total_energy_kwh" fill="#6aa7ff" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="muted">Nessun dato mensile disponibile per il periodo selezionato.</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

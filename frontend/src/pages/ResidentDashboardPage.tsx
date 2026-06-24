import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { ResidentSummaryResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ResidentQueueCard } from "../shared/ui/ResidentQueueCard";
import {
  DateRange,
  DateRangeControls,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHead,
  StatusBadge,
  Surface,
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
          <div style={{ gridColumn: "span 12" }}>
            <Surface
              title="Panoramica personale"
              subtitle="Numeri chiari, costi stimati e accesso rapido ai dati piu importanti"
              className="surface--accent hero-card"
              aside={<StatusBadge tone="neutral" label="Periodo selezionato" />}
            >
              <div className="grid">
                <MetricCard
                  className=""
                  label="Ricariche totali"
                  value={summaryQuery.data.total_sessions}
                  meta="Sessioni incluse nel periodo"
                  icon="01"
                  accent
                />
                <MetricCard
                  label="Energia totale"
                  value={`${formatNumber(summaryQuery.data.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`}
                  meta={`${formatNumber(summaryQuery.data.total_energy_wh)} Wh registrati`}
                  icon="kWh"
                />
                <MetricCard
                  label="Spesa stimata"
                  value={formatCurrencyEur(summaryQuery.data.estimated_cost_eur)}
                  meta={`Tariffa: ${formatCurrencyEur(summaryQuery.data.energy_price_eur_per_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}/kWh`}
                  icon="EUR"
                />
                <MetricCard
                  label="Proiezione annuale"
                  value={formatCurrencyEur(summaryQuery.data.estimated_annual_cost_eur)}
                  meta="Basata sull'uso del periodo selezionato"
                  icon="12M"
                />
              </div>
            </Surface>
          </div>

          <div style={{ gridColumn: "span 7" }}>
            <Surface title="Ultima ricarica" subtitle="Il tuo ultimo evento importato">
              {summaryQuery.data.latest_session ? (
                <div className="stack">
                  <div className="row">
                    <StatusBadge tone="ok" label="Registrata" />
                    <StatusBadge tone="neutral" label={formatDateTime(summaryQuery.data.latest_session.end_time)} />
                  </div>
                  <div className="detail-grid">
                    <div className="detail-card kv">
                      <div className="kv__label">Energia</div>
                      <div className="kv__value">{formatKwhFromWh(summaryQuery.data.latest_session.energy_wh)} kWh</div>
                    </div>
                    <div className="detail-card kv">
                      <div className="kv__label">Durata</div>
                      <div className="kv__value">{summaryQuery.data.latest_session.total_minutes} min</div>
                    </div>
                  </div>
                </div>
              ) : (
                <EmptyState title="Nessuna ricarica recente" message="Seleziona un periodo piu ampio per vedere le sessioni importate." />
              )}
            </Surface>
          </div>

          <div style={{ gridColumn: "span 5" }}>
            <Surface title="Tessere collegate" subtitle="RFID associati al tuo profilo">
              {summaryQuery.data.cards.length ? (
                <div className="list">
                  {summaryQuery.data.cards.map((c) => (
                    <div key={c.id} className="list-item">
                      <div>
                        <div className="list-item__title">{c.name ?? "Tessera senza nome"}</div>
                        <div className="list-item__meta">ID {c.rfid_id}</div>
                      </div>
                      <StatusBadge tone="neutral" label="Attiva" />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Nessuna tessera collegata" message="Contatta l'amministratore per associare una tessera RFID al tuo account." />
              )}
            </Surface>
          </div>

          <div style={{ gridColumn: "span 6" }}>
            <Surface title="Andamento mensile" subtitle="Ultimi mesi disponibili">
              {summaryQuery.data.monthly_breakdown.length ? (
                <div className="list">
                  {summaryQuery.data.monthly_breakdown.map((month) => (
                    <div key={month.month} className="list-item">
                      <div>
                        <div className="list-item__title">{month.month}</div>
                        <div className="list-item__meta">{formatCurrencyEur(month.estimated_cost_eur)} stimati</div>
                      </div>
                      <StatusBadge
                        tone="neutral"
                        label={`${formatNumber(month.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Andamento non disponibile" message="Non ci sono dati mensili nel periodo selezionato." />
              )}
            </Surface>
          </div>

          <ResidentQueueCard />
        </div>
      ) : null}
    </div>
  );
}

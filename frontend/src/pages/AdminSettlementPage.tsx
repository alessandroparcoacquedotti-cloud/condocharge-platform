import { useMemo } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { SettlementSummaryResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatCurrencyEur, formatNumber } from "../shared/ui";

export default function AdminSettlementPage() {
  const fetcher = useMemo(() => () => endpoints.adminSettlementSummary(), []);
  const query = useQuery<SettlementSummaryResponse>(fetcher);

  return (
    <div>
      <PageHead title="Riepilogo" subtitle="Riepilogo incassi e stato complessivo dei periodi (strumento operativo)" />

      {query.loading ? <LoadingState label="Caricamento riepilogo…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare il riepilogo" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="grid">
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Totale addebitato</div>
            <div className="metric">{formatCurrencyEur(query.data.total_billed_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Registrato</div>
            <div className="metric">{formatCurrencyEur(query.data.paid_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Non pagato</div>
            <div className="metric">{formatCurrencyEur(query.data.unpaid_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 3" }}>
            <div className="card-title">Annullato</div>
            <div className="metric">{formatCurrencyEur(query.data.waived_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Tasso incasso</div>
            <div className="metric">{formatNumber(query.data.collection_rate, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%</div>
          </div>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Periodi aperti</div>
            <div className="metric">{query.data.open_periods}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Periodi chiusi</div>
            <div className="metric">{query.data.closed_periods}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

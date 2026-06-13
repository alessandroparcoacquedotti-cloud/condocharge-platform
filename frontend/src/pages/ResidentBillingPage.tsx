import { useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import { useAuth } from "../shared/auth/AuthProvider";
import type { BillingStatementDetailResponse, BillingStatementResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatDateTime, formatKwhFromWh, formatCurrencyEur, formatNumber } from "../shared/ui";

function durationLabel(totalMinutes: number | null | undefined) {
  if (totalMinutes == null) return "-";
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}h ${m}m`;
}

export default function ResidentBillingPage() {
  const auth = useAuth();
  const listFetcher = useMemo(() => () => endpoints.residentBillingStatements(), []);
  const listQuery = useQuery<BillingStatementResponse[]>(listFetcher);
  const [selectedStatementId, setSelectedStatementId] = useState<number | null>(null);

  useEffect(() => {
    if (!selectedStatementId && listQuery.data?.length) {
      setSelectedStatementId(listQuery.data[0].id);
    }
  }, [listQuery.data, selectedStatementId]);

  const detailFetcher = useMemo(
    () => () => (selectedStatementId ? endpoints.residentBillingStatement(selectedStatementId) : Promise.resolve(null)),
    [selectedStatementId],
  );
  const detailQuery = useQuery<BillingStatementDetailResponse | null>(detailFetcher);
  const [exportingId, setExportingId] = useState<number | null>(null);

  async function exportPdf(statementId: number) {
    setExportingId(statementId);
    try {
      const res = await endpoints.exportResidentBillingStatementPdf(statementId);
      if (!res.ok) throw new Error(`Esportazione non riuscita (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `statement_${statementId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExportingId(null);
    }
  }

  return (
    <div>
      <PageHead
        title="Le mie spese"
        subtitle="Consulta consumi e importi stimati. I documenti di addebito sono facoltativi e gestiti dall'amministratore."
      />
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="card-title">Contatti</div>
        <div className="muted">Email: {auth.user?.email ?? "Non impostata"}</div>
      </div>

      {listQuery.loading ? <LoadingState label="Caricamento documenti…" /> : null}
      {listQuery.error ? <ErrorState title="Impossibile caricare i documenti" message={listQuery.error} onRetry={listQuery.refetch} /> : null}

      {listQuery.data ? (
        <div className="card">
          <div className="card-title">Documenti di addebito</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Periodo</th>
                  <th>Documento</th>
                  <th>Ricariche</th>
                  <th>kWh</th>
                  <th>Importo</th>
                  <th>Residuo</th>
                  <th>Stato</th>
                  <th>PDF</th>
                </tr>
              </thead>
              <tbody>
                {listQuery.data.map((statement) => (
                  <tr
                    key={statement.id}
                    onClick={() => setSelectedStatementId(statement.id)}
                    style={{ cursor: "pointer", opacity: selectedStatementId === statement.id ? 1 : 0.85 }}
                  >
                    <td style={{ fontWeight: 700 }}>{statement.period_name}</td>
                    <td>{statement.statement_number}</td>
                    <td>{statement.sessions_count}</td>
                    <td>{formatNumber(statement.energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                    <td>{formatCurrencyEur(statement.amount_eur)}</td>
                    <td>{formatCurrencyEur(statement.amount_due_eur)}</td>
                    <td>{statement.payment_status}</td>
                    <td>
                      <button
                        className="btn"
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          exportPdf(statement.id);
                        }}
                        disabled={exportingId === statement.id}
                      >
                        {exportingId === statement.id ? "Esportazione…" : "PDF"}
                      </button>
                    </td>
                  </tr>
                ))}
                {!listQuery.data.length ? (
                  <tr>
                    <td colSpan={8} className="muted">
                      Nessun documento disponibile.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {detailQuery.loading ? <LoadingState label="Caricamento dettaglio…" /> : null}
      {detailQuery.error ? <ErrorState title="Impossibile caricare il dettaglio" message={detailQuery.error} onRetry={detailQuery.refetch} /> : null}

      {detailQuery.data ? (
        (() => {
          const detail = detailQuery.data;
          return (
        <div className="grid" style={{ marginTop: 12 }}>
          <div className="card" style={{ gridColumn: "span 4" }}>
            <div className="card-title">Periodo</div>
            <div className="metric" style={{ fontSize: 20 }}>{detail.period_name}</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {formatDateTime(detail.period_start)} - {formatDateTime(detail.period_end)}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {detail.statement_number}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              Riferimento: <strong>{detail.payment_reference}</strong>
            </div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">Ricariche</div>
            <div className="metric">{detail.sessions_count}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">kWh</div>
            <div className="metric">{formatNumber(detail.energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">Importo</div>
            <div className="metric">{formatCurrencyEur(detail.amount_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">Registrato</div>
            <div className="metric">{formatCurrencyEur(detail.amount_paid_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">Residuo</div>
            <div className="metric">{formatCurrencyEur(detail.amount_due_eur)}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 2" }}>
            <div className="card-title">Stato</div>
            <div className="metric" style={{ fontSize: 18 }}>{detail.payment_status}</div>
          </div>
          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">PDF</div>
            <button className="btn" type="button" disabled={exportingId === detail.id} onClick={() => exportPdf(detail.id)}>
              {exportingId === detail.id ? "Esportazione…" : "Esporta PDF"}
            </button>
          </div>

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Pagamenti registrati (informativo)</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Importo</th>
                    <th>Metodo</th>
                    <th>Riferimento</th>
                    <th>Nota</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{formatDateTime(p.received_at)}</td>
                      <td>{formatCurrencyEur(p.amount_eur)}</td>
                      <td>{p.method}</td>
                      <td>{p.transaction_reference ?? "-"}</td>
                      <td>{p.note ?? "-"}</td>
                    </tr>
                  ))}
                  {!detail.payments.length ? (
                    <tr>
                      <td colSpan={5} className="muted">Nessun pagamento registrato.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ gridColumn: "span 12" }}>
            <div className="card-title">Ricariche incluse</div>
            <div className="muted" style={{ marginBottom: 10 }}>
              Prezzo energia (snapshot): {formatCurrencyEur(detail.energy_price_eur_per_kwh_snapshot, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}/kWh
            </div>
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
                  {detail.sessions.map((session) => (
                    <tr key={session.id}>
                      <td>
                        <div style={{ fontWeight: 700 }}>{session.station?.host ?? `#${session.station_id}`}</div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          {session.station?.name ?? ""}
                        </div>
                      </td>
                      <td>
                        <div style={{ fontWeight: 700 }}>{session.rfid_user?.name ?? "-"}</div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          {session.rfid_user?.rfid_id ?? "-"}
                        </div>
                      </td>
                      <td>{formatDateTime(session.start_time)}</td>
                      <td>{formatDateTime(session.end_time)}</td>
                      <td>{formatKwhFromWh(session.energy_wh)}</td>
                      <td>{durationLabel(session.total_minutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
          );
        })()
      ) : null}
    </div>
  );
}

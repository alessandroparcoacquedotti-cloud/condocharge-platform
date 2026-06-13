import { useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { UserListResponse } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatKwhFromWh } from "../shared/ui";

const DEFAULT_LIMIT = 20;

export default function UsersPage() {
  const [offset, setOffset] = useState(0);

  const fetcher = useMemo(
    () => () => endpoints.users({ limit: DEFAULT_LIMIT, offset }),
    [offset],
  );
  const query = useQuery<UserListResponse>(fetcher);

  const total = query.data?.pagination.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + DEFAULT_LIMIT < total;

  return (
    <div>
      <PageHead
        title="Utenti"
        subtitle="Tessere RFID rilevate dalle ricariche importate"
        right={
          <div className="pill">
            Endpoint: <span className="muted">/api/v1/users</span>
          </div>
        }
      />

      {query.loading ? <LoadingState label="Caricamento utenti…" /> : null}
      {query.error ? <ErrorState title="Impossibile caricare gli utenti" message={query.error} onRetry={query.refetch} /> : null}

      {query.data ? (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Utente</th>
                  <th>Tessera</th>
                  <th>Ricariche totali</th>
                  <th>Energia totale (kWh)</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((u) => (
                  <tr key={u.id}>
                    <td style={{ fontWeight: 700 }}>{u.name ?? `Utente #${u.id}`}</td>
                    <td>{u.rfid_id}</td>
                    <td>{u.session_count ?? 0}</td>
                    <td>{formatKwhFromWh(u.total_energy_wh)}</td>
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

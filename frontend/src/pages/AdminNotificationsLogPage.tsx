import { useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { AdminNotificationLogListResponse, AdminNotificationLogRow } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatDateTime } from "../shared/ui";

function statusPillClass(status: string) {
  if (status === "sent") return "pill is-ok";
  if (status === "failed") return "pill is-danger";
  return "pill";
}

function formatResident(row: AdminNotificationLogRow) {
  const email = row.resident_email ? ` · ${row.resident_email}` : "";
  return `${row.resident_username} (#${row.resident_app_user_id})${email}`;
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia("(max-width: 720px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 720px)");
    const onChange = () => setIsMobile(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}

export default function AdminNotificationsLogPage() {
  const isMobile = useIsMobile();
  const [notificationType, setNotificationType] = useState("");
  const [status, setStatus] = useState("");
  const [residentId, setResidentId] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);

  const parsedResidentId = useMemo(() => {
    const v = Number(residentId);
    if (!residentId.trim()) return undefined;
    if (!Number.isFinite(v) || v <= 0) return undefined;
    return Math.floor(v);
  }, [residentId]);

  const query = useQuery(
    useMemo(
      () => () =>
        endpoints.adminNotificationLogs({
          notification_type: notificationType || undefined,
          status: status || undefined,
          resident_app_user_id: parsedResidentId,
          limit,
          offset,
        }),
      [notificationType, status, parsedResidentId, limit, offset],
    ),
  );

  const data: AdminNotificationLogListResponse | null = query.data;
  const items = data?.items ?? [];
  const total = data?.pagination.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  useEffect(() => {
    setOffset(0);
  }, [notificationType, status, parsedResidentId, limit]);

  if (query.loading) return <LoadingState label="Caricamento log notifiche…" />;
  if (query.error) return <ErrorState title="Log notifiche" message={query.error} onRetry={query.refetch} />;

  return (
    <div>
      <PageHead
        title="Log notifiche"
        subtitle="Solo lettura. Utile per verificare anteprime (SMTP disabilitato) e deduplica."
      />

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <div className="pill">
              Tipo:&nbsp;
              <select
                value={notificationType}
                onChange={(e) => setNotificationType(e.target.value)}
                style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}
              >
                <option value="">Tutti</option>
                <option value="station_available">station_available</option>
                <option value="charging_completed">charging_completed</option>
              </select>
            </div>

            <div className="pill">
              Stato:&nbsp;
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}
              >
                <option value="">Tutti</option>
                <option value="preview">preview</option>
                <option value="sent">sent</option>
                <option value="failed">failed</option>
              </select>
            </div>

            <div className="pill">
              Resident ID:&nbsp;
              <input
                value={residentId}
                onChange={(e) => setResidentId(e.target.value)}
                placeholder="es. 12"
                inputMode="numeric"
                style={{ width: 110, background: "transparent", border: "none", outline: "none", color: "inherit" }}
              />
            </div>

            <div className="pill">
              Limite:&nbsp;
              <select
                value={String(limit)}
                onChange={(e) => setLimit(Number(e.target.value))}
                style={{ background: "transparent", border: "none", outline: "none", color: "inherit" }}
              >
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </div>
          </div>

          <div className="row">
            <button className="btn" type="button" onClick={() => setOffset((v) => Math.max(0, v - limit))} disabled={!canPrev}>
              ← Precedenti
            </button>
            <button className="btn" type="button" onClick={() => setOffset((v) => v + limit)} disabled={!canNext}>
              Successivi →
            </button>
          </div>
        </div>

        <div className="muted" style={{ marginTop: 10 }}>
          Totale: {total} · Offset: {offset}
          {query.refreshing ? " · Aggiornamento…" : ""}
        </div>
      </div>

      {items.length === 0 ? (
        <div className="card">
          <div className="muted">Nessuna notifica trovata con i filtri correnti.</div>
        </div>
      ) : isMobile ? (
        <div className="grid">
          {items.map((row) => (
            <div key={row.id} className="card">
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                <div className="muted">{formatDateTime(row.created_at)}</div>
                <div className={statusPillClass(row.status)}>{row.status}</div>
              </div>
              <div style={{ fontWeight: 700 }}>{formatResident(row)}</div>
              <div className="muted" style={{ marginTop: 6 }}>
                Tipo: {row.notification_type}
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                Dedupe: {row.dedupe_key}
              </div>
              {row.error_message ? (
                <div className="muted" style={{ marginTop: 6, color: "var(--danger)" }}>
                  Errore: {row.error_message}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Resident</th>
                <th>Tipo</th>
                <th>Stato</th>
                <th>Errore</th>
                <th>Dedupe key</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div>{formatDateTime(row.created_at)}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      sent_at: {formatDateTime(row.sent_at)}
                    </div>
                  </td>
                  <td>
                    <div style={{ fontWeight: 700 }}>{row.resident_username}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      #{row.resident_app_user_id}
                      {row.resident_email ? ` · ${row.resident_email}` : ""}
                    </div>
                  </td>
                  <td>{row.notification_type}</td>
                  <td>
                    <span className={statusPillClass(row.status)}>{row.status}</span>
                  </td>
                  <td className="muted" style={{ maxWidth: 260 }}>
                    {row.error_message || "-"}
                  </td>
                  <td className="muted" style={{ maxWidth: 320 }}>
                    {row.dedupe_key}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


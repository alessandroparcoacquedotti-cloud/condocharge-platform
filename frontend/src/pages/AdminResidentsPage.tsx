import { FormEvent, useEffect, useMemo, useState } from "react";

import { endpoints } from "../shared/api/endpoints";
import type { AdminResidentRow, AdminRfidUserRow } from "../shared/api/types";
import { useQuery } from "../shared/hooks/useQuery";
import { ErrorState, LoadingState, PageHead, formatCurrencyEur, formatDateTime, formatNumber } from "../shared/ui";

type ResidentEdit = {
  first_name: string;
  last_name: string;
  apartment_or_unit: string;
  email: string;
  phone_number: string;
  is_active: boolean;
};

function invitationBadge(row: AdminResidentRow) {
  if (row.invitation_status === "active") return <span className="pill is-ok">Active</span>;
  if (row.invitation_status === "invited") return <span className="pill">Invited</span>;
  return <span className="pill is-danger">Invitation Expired</span>;
}

export default function AdminResidentsPage() {
  const residentsFetcher = useMemo(() => () => endpoints.adminResidents(), []);
  const rfidFetcher = useMemo(() => () => endpoints.adminRfidUsers(), []);
  const residentsQuery = useQuery<AdminResidentRow[]>(residentsFetcher);
  const rfidQuery = useQuery<AdminRfidUserRow[]>(rfidFetcher);

  const residentOptions = useMemo(
    () => (residentsQuery.data ?? []).filter((row) => row.role === "resident"),
    [residentsQuery.data],
  );

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [apartmentOrUnit, setApartmentOrUnit] = useState("");
  const [email, setEmail] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const [assignments, setAssignments] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);

  const [residentEdits, setResidentEdits] = useState<Record<number, ResidentEdit>>({});
  const [savingResidentId, setSavingResidentId] = useState<number | null>(null);
  const [invitingResidentId, setInvitingResidentId] = useState<number | null>(null);
  const [forcingResidentId, setForcingResidentId] = useState<number | null>(null);

  useEffect(() => {
    if (!rfidQuery.data) return;
    const next: Record<number, string> = {};
    for (const row of rfidQuery.data) {
      next[row.id] = row.app_user_id != null ? String(row.app_user_id) : "";
    }
    setAssignments(next);
  }, [rfidQuery.data]);

  useEffect(() => {
    if (!residentsQuery.data) return;
    const next: Record<number, ResidentEdit> = {};
    for (const row of residentsQuery.data) {
      if (row.role !== "resident") continue;
      next[row.app_user_id] = {
        first_name: row.first_name ?? "",
        last_name: row.last_name ?? "",
        apartment_or_unit: row.apartment_or_unit ?? "",
        email: row.email ?? "",
        phone_number: row.phone_number ?? "",
        is_active: row.is_active,
      };
    }
    setResidentEdits(next);
  }, [residentsQuery.data]);

  async function handleCreateResident(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const created = await endpoints.createResident({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        apartment_or_unit: apartmentOrUnit.trim(),
        email: email.trim(),
        phone_number: phoneNumber.trim() || null,
      });
      setFirstName("");
      setLastName("");
      setApartmentOrUnit("");
      setEmail("");
      setPhoneNumber("");
      setActionMessage(
        `Residente creato con username ${created.resident.username}. Invito inviato automaticamente e valido fino a ${formatDateTime(created.invitation_expires_at)}.`,
      );
      residentsQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile creare il residente");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResidentSave(residentId: number) {
    const edit = residentEdits[residentId];
    if (!edit) return;
    setSavingResidentId(residentId);
    setActionError(null);
    setActionMessage(null);
    try {
      await endpoints.updateResident(residentId, {
        first_name: edit.first_name.trim() || null,
        last_name: edit.last_name.trim() || null,
        apartment_or_unit: edit.apartment_or_unit.trim() || null,
        email: edit.email.trim() || null,
        phone_number: edit.phone_number.trim() || null,
        is_active: edit.is_active,
      });
      setActionMessage("Residente aggiornato.");
      residentsQuery.refetch();
      rfidQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile aggiornare il residente");
    } finally {
      setSavingResidentId(null);
    }
  }

  async function handleInviteResident(residentId: number) {
    setInvitingResidentId(residentId);
    setActionError(null);
    setActionMessage(null);
    try {
      const resp = await endpoints.inviteResident(residentId);
      const resident = (residentsQuery.data ?? []).find((r) => r.app_user_id === residentId);
      setActionMessage(
        `Invito inviato a ${resident?.email ?? resident?.username ?? `#${residentId}`}. Scadenza: ${formatDateTime(resp.invitation_expires_at)}.`,
      );
      residentsQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile inviare l'invito");
    } finally {
      setInvitingResidentId(null);
    }
  }

  async function handleForcePasswordChange(residentId: number) {
    setForcingResidentId(residentId);
    setActionError(null);
    setActionMessage(null);
    try {
      await endpoints.forceResidentPasswordChange(residentId);
      setActionMessage("Cambio password forzato al prossimo accesso.");
      residentsQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile forzare il cambio password");
    } finally {
      setForcingResidentId(null);
    }
  }

  async function handleAssign(rfidUserId: number) {
    setSavingId(rfidUserId);
    setActionError(null);
    setActionMessage(null);
    try {
      const raw = assignments[rfidUserId] ?? "";
      await endpoints.assignRfidUser(rfidUserId, { app_user_id: raw ? Number(raw) : null });
      residentsQuery.refetch();
      rfidQuery.refetch();
    } catch (err) {
      setActionError(typeof err === "object" && err && "message" in err ? String((err as any).message) : "Impossibile assegnare la tessera");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div>
      <PageHead title="Condomini" subtitle="Gestisci residenti, contatti e assegnazioni tessere RFID nel condominio" />

      {(residentsQuery.loading || rfidQuery.loading) && <LoadingState label="Caricamento gestione…" />}
      {residentsQuery.error ? <ErrorState title="Impossibile caricare i residenti" message={residentsQuery.error} onRetry={residentsQuery.refetch} /> : null}
      {rfidQuery.error ? <ErrorState title="Impossibile caricare le tessere RFID" message={rfidQuery.error} onRetry={rfidQuery.refetch} /> : null}
      {actionError ? <ErrorState title="Operazione non riuscita" message={actionError} /> : null}
      {actionMessage ? <div className="muted">{actionMessage}</div> : null}

      <div className="grid">
        <div className="card" style={{ gridColumn: "span 4" }}>
          <div className="card-title">Crea residente</div>
          <form className="auth-form" onSubmit={handleCreateResident}>
            <label className="auth-label">
              Nome
              <input className="auth-input" value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
            </label>
            <label className="auth-label">
              Cognome
              <input className="auth-input" value={lastName} onChange={(e) => setLastName(e.target.value)} required />
            </label>
            <label className="auth-label">
              Unità (appartamento)
              <input className="auth-input" value={apartmentOrUnit} onChange={(e) => setApartmentOrUnit(e.target.value)} required />
            </label>
            <label className="auth-label">
              Email
              <input className="auth-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="auth-label">
              Telefono (opzionale)
              <input className="auth-input" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} />
            </label>
            <button
              className="btn"
              type="submit"
              disabled={submitting || !firstName.trim() || !lastName.trim() || !apartmentOrUnit.trim() || !email.trim()}
            >
              {submitting ? "Creazione…" : "Crea residente"}
            </button>
          </form>
        </div>

        <div className="card" style={{ gridColumn: "span 8" }}>
          <div className="card-title">Assegnazione tessere RFID</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Tessera</th>
                  <th>Nome rilevato</th>
                  <th>Residente assegnato</th>
                  <th>Azione</th>
                </tr>
              </thead>
              <tbody>
                {(rfidQuery.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td style={{ fontWeight: 700 }}>{row.rfid_id}</td>
                    <td>{row.name ?? "-"}</td>
                    <td>
                      <select
                        className="auth-input"
                        value={assignments[row.id] ?? ""}
                        onChange={(e) => setAssignments((prev) => ({ ...prev, [row.id]: e.target.value }))}
                      >
                        <option value="">Non assegnata</option>
                        {residentOptions.map((resident) => (
                          <option key={resident.app_user_id} value={resident.app_user_id}>
                            {resident.username} {resident.apartment_or_unit ? `(${resident.apartment_or_unit})` : ""}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <button className="btn" type="button" disabled={savingId === row.id} onClick={() => handleAssign(row.id)}>
                        {savingId === row.id ? "Salvataggio…" : "Salva"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card" style={{ gridColumn: "span 12" }}>
          <div className="card-title">Residenti</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Nome utente</th>
                  <th>Nome</th>
                  <th>Cognome</th>
                  <th>Unità</th>
                  <th>Email</th>
                  <th>Telefono</th>
                  <th>Stato</th>
                  <th>Invito</th>
                  <th>Ultimo accesso</th>
                  <th>Tessere</th>
                  <th>kWh</th>
                  <th>Costo</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {residentOptions.map((row) => {
                  const edit = residentEdits[row.app_user_id];
                  return (
                    <tr key={row.app_user_id}>
                      <td style={{ fontWeight: 800 }}>{row.username}</td>
                      <td>
                        <input
                          className="auth-input"
                          value={edit?.first_name ?? ""}
                          onChange={(e) => setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), first_name: e.target.value } }))}
                        />
                      </td>
                      <td>
                        <input
                          className="auth-input"
                          value={edit?.last_name ?? ""}
                          onChange={(e) => setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), last_name: e.target.value } }))}
                        />
                      </td>
                      <td>
                        <input
                          className="auth-input"
                          value={edit?.apartment_or_unit ?? ""}
                          onChange={(e) =>
                            setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), apartment_or_unit: e.target.value } }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          className="auth-input"
                          type="email"
                          value={edit?.email ?? ""}
                          onChange={(e) => setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), email: e.target.value } }))}
                        />
                      </td>
                      <td>
                        <input
                          className="auth-input"
                          value={edit?.phone_number ?? ""}
                          onChange={(e) =>
                            setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), phone_number: e.target.value } }))
                          }
                        />
                      </td>
                      <td>
                        <label className="row" style={{ justifyContent: "flex-start" }}>
                          <input
                            type="checkbox"
                            checked={!!edit?.is_active}
                            onChange={(e) =>
                              setResidentEdits((prev) => ({ ...prev, [row.app_user_id]: { ...(prev[row.app_user_id] ?? edit), is_active: e.target.checked } }))
                            }
                          />
                          <span>{edit?.is_active ? "Attivo" : "Disattivo"}</span>
                        </label>
                      </td>
                      <td>
                        <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
                          {invitationBadge(row)}
                          {row.invitation_expires_at ? (
                            <span className="muted" style={{ fontSize: 12 }}>
                              scade: {formatDateTime(row.invitation_expires_at)}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td>{formatDateTime(row.last_login_at ?? null)}</td>
                      <td>
                        {row.linked_cards.length ? row.linked_cards.map((card) => card.rfid_id).join(", ") : <span className="muted">Nessuna</span>}
                      </td>
                      <td>{formatNumber(row.total_energy_kwh, { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                      <td>{formatCurrencyEur(row.estimated_cost_eur)}</td>
                      <td>
                        <div className="row" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
                          <button className="btn" type="button" disabled={savingResidentId === row.app_user_id} onClick={() => handleResidentSave(row.app_user_id)}>
                            {savingResidentId === row.app_user_id ? "Salvataggio…" : "Salva"}
                          </button>
                          <button
                            className="btn"
                            type="button"
                            disabled={invitingResidentId === row.app_user_id || !row.email}
                            onClick={() => handleInviteResident(row.app_user_id)}
                          >
                            {invitingResidentId === row.app_user_id
                              ? "Invio…"
                              : row.invitation_sent_at
                                ? "Reinvia invito"
                                : "Invia invito"}
                          </button>
                          <button
                            className="btn"
                            type="button"
                            disabled={forcingResidentId === row.app_user_id}
                            onClick={() => handleForcePasswordChange(row.app_user_id)}
                          >
                            {forcingResidentId === row.app_user_id ? "Invio…" : "Forza cambio"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

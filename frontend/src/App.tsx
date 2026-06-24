import { Suspense, lazy, useMemo, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import { RequireAuth, RequireRole } from "./shared/auth/RequireAuth";
import { useAuth } from "./shared/auth/AuthProvider";
import { LoadingState } from "./shared/ui";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const StationsPage = lazy(() => import("./pages/StationsPage"));
const SessionsPage = lazy(() => import("./pages/SessionsPage"));
const UsersPage = lazy(() => import("./pages/UsersPage"));
const ResidentDashboardPage = lazy(() => import("./pages/ResidentDashboardPage"));
const ResidentBillingPage = lazy(() => import("./pages/ResidentBillingPage"));
const ResidentStationsStatusPage = lazy(() => import("./pages/ResidentStationsStatusPage"));
const ResidentSessionsPage = lazy(() => import("./pages/ResidentSessionsPage"));
const ResidentNotificationsPage = lazy(() => import("./pages/ResidentNotificationsPage"));
const ResidentProfilePage = lazy(() => import("./pages/ResidentProfilePageTelegramV11"));
const ResidentTelegramPage = lazy(() => import("./pages/ResidentProfilePage"));
const ResidentChangePasswordPage = lazy(() => import("./pages/ResidentChangePasswordPage"));
const InvitationPage = lazy(() => import("./pages/InvitationPage"));
const AdminResidentsPage = lazy(() => import("./pages/AdminResidentsPage"));
const AdminCostReportPage = lazy(() => import("./pages/AdminCostReportPage"));
const AdminSettingsPage = lazy(() => import("./pages/AdminSettingsPage"));
const AdminBillingPage = lazy(() => import("./pages/AdminBillingPage"));
const AdminReconciliationPage = lazy(() => import("./pages/AdminReconciliationPage"));
const AdminSettlementPage = lazy(() => import("./pages/AdminSettlementPage"));
const AdminRemindersPage = lazy(() => import("./pages/AdminRemindersPage"));
const AdminNotificationsLogPage = lazy(() => import("./pages/AdminNotificationsLogPage"));

function roleLabel(role: string | undefined) {
  if (role === "admin") return "Amministratore";
  if (role === "resident") return "Condomino";
  if (role === "viewer") return "Visualizzatore";
  return role ?? "-";
}

function useMobileMenu() {
  const [open, setOpen] = useState(false);
  return useMemo(
    () => ({
      open,
      toggle() {
        setOpen((v) => !v);
      },
      close() {
        setOpen(false);
      },
    }),
    [open],
  );
}

function AdminLayout() {
  const auth = useAuth();
  const role = auth.user?.role;
  const menu = useMobileMenu();
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__inner">
          <div className="shell-top">
            <div className="shell-top__main">
              <div className="brand">
                <div className="brand__mark" aria-hidden="true">
                  C
                </div>
                <div className="brand__copy">
                  <div className="brand__title">
                    <span className="brand-word brand-word--condo">Condo</span>{" "}
                    <span className="brand-word brand-word--charge">Charge</span>
                  </div>
                  <div className="brand__subtitle">Gestione ricariche condominiali</div>
                </div>
              </div>
              <div className="shell-meta">
                <div className="pill">{auth.user?.condominium.name ?? "-"}</div>
                <div className="pill">{auth.user?.username ?? "-"}</div>
                <div className="pill">{roleLabel(auth.user?.role)}</div>
              </div>
            </div>

            <div className="shell-top__actions">
              <button className="nav-toggle btn btn--secondary" type="button" onClick={menu.toggle} aria-expanded={menu.open}>
                Menu
              </button>
              <button className="btn btn--secondary" type="button" onClick={auth.logout}>
                Esci
              </button>
            </div>
          </div>

          <nav className={menu.open ? "nav nav--open" : "nav"} onClick={() => menu.close()}>
            <NavLink to="/admin/panoramica" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Panoramica
            </NavLink>
            <NavLink to="/admin/colonnine" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Colonnine
            </NavLink>
            <NavLink to="/admin/ricariche" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Ricariche
            </NavLink>
            {role === "admin" ? (
              <>
                <NavLink to="/admin/condomini" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                  Condomini
                </NavLink>
                <NavLink to="/admin/costi" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                  Costi
                </NavLink>
                <NavLink to="/admin/impostazioni" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                  Impostazioni
                </NavLink>

                <details className="nav-advanced" onClick={(e) => e.stopPropagation()}>
                  <summary className="nav__link">Avanzate</summary>
                  <div className="nav-advanced__items">
                    <NavLink to="/admin/addebiti" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                      Addebiti
                    </NavLink>
                    <NavLink to="/admin/verifiche" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                      Verifiche
                    </NavLink>
                    <NavLink to="/admin/notifiche" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                      Notifiche
                    </NavLink>
                    <NavLink to="/admin/log-notifiche" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                      Log notifiche
                    </NavLink>
                    <NavLink to="/admin/riepilogo" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
                      Riepilogo
                    </NavLink>
                  </div>
                </details>
              </>
            ) : null}
          </nav>
        </div>
      </header>

      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}

function ResidentLayout() {
  const auth = useAuth();
  const menu = useMobileMenu();
  return (
    <div className="app-shell">
      <header className="app-header app-header--resident">
        <div className="app-header__inner">
          <div className="resident-header">
            <div className="brand brand--compact">
              <div className="brand__mark brand__mark--compact" aria-hidden="true">
                C
              </div>
              <div className="brand__title brand__title--compact">
                <span className="brand-word brand-word--condo">Condo</span>{" "}
                <span className="brand-word brand-word--charge">Charge</span>
              </div>
            </div>

            <button
              className="icon-btn"
              type="button"
              onClick={menu.toggle}
              aria-label="Menu"
              aria-expanded={menu.open}
            >
              ☰
            </button>
          </div>

          <nav className={menu.open ? "nav nav--open" : "nav"} onClick={() => menu.close()}>
            <NavLink to="/resident/stato-colonnine" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Stato colonnine
            </NavLink>
            <NavLink to="/resident/profilo" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Profilo
            </NavLink>
            <NavLink to="/resident/telegram" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Telegram
            </NavLink>
            <NavLink to="/resident/notifiche" className={({ isActive }) => (isActive ? "nav__link is-active" : "nav__link")}>
              Notifiche
            </NavLink>
            <button className="nav__link" type="button" onClick={auth.logout}>
              Esci
            </button>
          </nav>
        </div>
      </header>

      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}

function HomeRedirect() {
  const auth = useAuth();
  if (!auth.user) return <Navigate to="/login" replace />;
  if (auth.user.role === "resident") {
    if (auth.user.must_change_password) return <Navigate to="/resident/cambia-password" replace />;
    return <Navigate to="/resident/stato-colonnine" replace />;
  }
  return <Navigate to="/admin/panoramica" replace />;
}

function RequirePasswordChanged(props: { children: JSX.Element }) {
  const auth = useAuth();
  if (auth.user?.role === "resident" && auth.user.must_change_password) {
    return <Navigate to="/resident/cambia-password" replace />;
  }
  return props.children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/invite/:token"
        element={
          <Suspense fallback={<LoadingState label="Caricamento invito…" />}>
            <InvitationPage />
          </Suspense>
        }
      />
      <Route element={<RequireAuth><Outlet /></RequireAuth>}>
        <Route path="/" element={<HomeRedirect />} />

        <Route element={<AdminLayout />}>
          <Route
            path="/admin"
            element={
              <RequireRole allow={["admin", "viewer"]}>
                <Navigate to="/admin/panoramica" replace />
              </RequireRole>
            }
          />
          <Route
            path="/admin/panoramica"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin", "viewer"]}>
                  <DashboardPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/colonnine"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin", "viewer"]}>
                  <StationsPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/ricariche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin", "viewer"]}>
                  <SessionsPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/utenti"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin", "viewer"]}>
                  <UsersPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/condomini"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminResidentsPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/costi"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminCostReportPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/impostazioni"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminSettingsPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/addebiti"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminBillingPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/verifiche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminReconciliationPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/notifiche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminRemindersPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/log-notifiche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminNotificationsLogPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/admin/riepilogo"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["admin"]}>
                  <AdminSettlementPage />
                </RequireRole>
              </Suspense>
            }
          />
        </Route>

        <Route element={<ResidentLayout />}>
          <Route
            path="/resident"
            element={
              <RequireRole allow={["resident"]}>
                <RequirePasswordChanged>
                  <Navigate to="/resident/stato-colonnine" replace />
                </RequirePasswordChanged>
              </RequireRole>
            }
          />
          <Route
            path="/resident/cambia-password"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <ResidentChangePasswordPage />
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/stato-colonnine"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentStationsStatusPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/ricariche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentSessionsPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/consumi"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentDashboardPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/spese"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentBillingPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/notifiche"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentNotificationsPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/telegram"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentTelegramPage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
          <Route
            path="/resident/profilo"
            element={
              <Suspense fallback={<LoadingState label="Caricamento pagina…" />}>
                <RequireRole allow={["resident"]}>
                  <RequirePasswordChanged>
                    <ResidentProfilePage />
                  </RequirePasswordChanged>
                </RequireRole>
              </Suspense>
            }
          />
        </Route>

        <Route path="/dashboard" element={<Navigate to="/admin/panoramica" replace />} />
        <Route path="/stations" element={<Navigate to="/admin/colonnine" replace />} />
        <Route path="/sessions" element={<Navigate to="/admin/ricariche" replace />} />
        <Route path="/users" element={<Navigate to="/admin/utenti" replace />} />
        <Route path="/admin/residents" element={<Navigate to="/admin/condomini" replace />} />
        <Route path="/admin/costs" element={<Navigate to="/admin/costi" replace />} />
        <Route path="/admin/settings" element={<Navigate to="/admin/impostazioni" replace />} />
        <Route path="/admin/billing" element={<Navigate to="/admin/addebiti" replace />} />
        <Route path="/admin/reconciliation" element={<Navigate to="/admin/verifiche" replace />} />
        <Route path="/admin/reminders" element={<Navigate to="/admin/notifiche" replace />} />
        <Route path="/admin/settlement" element={<Navigate to="/admin/riepilogo" replace />} />
        <Route path="/admin/notifications/logs" element={<Navigate to="/admin/log-notifiche" replace />} />

        <Route
          path="/resident/billing"
          element={
            <Navigate to="/resident/spese" replace />
          }
        />
      </Route>
    </Routes>
  );
}

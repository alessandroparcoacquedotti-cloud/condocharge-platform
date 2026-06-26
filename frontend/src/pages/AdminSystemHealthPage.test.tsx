import { render, screen, waitFor } from "@testing-library/react";

import AdminSystemHealthPage from "./AdminSystemHealthPage";

const mocks = vi.hoisted(() => ({
  adminSystemHealth: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    adminSystemHealth: mocks.adminSystemHealth,
  },
}));

describe("AdminSystemHealthPage", () => {
  beforeEach(() => {
    mocks.adminSystemHealth.mockResolvedValue({
      server_time: "2026-06-26T10:00:00Z",
      backend_ok: true,
      database_ok: true,
      railway_dns_ok: true,
      telegram_configured: false,
      push_configured: true,
      push_active_subscriptions: 3,
      agent_status: {
        agent_id: "agent-1",
        hostname: "mini-pc",
        agent_version: "0.1.0",
        online: true,
        health_color: "green",
        agent_started_at: "2026-06-26T09:00:00Z",
        last_heartbeat: "2026-06-26T10:00:00Z",
        last_heartbeat_sent_at: "2026-06-26T10:00:00Z",
        last_station_update: "2026-06-26T10:00:00Z",
        last_session_import: "2026-06-26T10:00:00Z",
        service_uptime_seconds: 3600,
        heartbeat_count: 1,
        polling_count: 2,
        import_count: 3,
        retry_count: 0,
        failure_count: 0,
      },
    });
  });

  it("renders status badges and agent card", async () => {
    render(<AdminSystemHealthPage />);

    await waitFor(() => expect(mocks.adminSystemHealth).toHaveBeenCalled());
    expect(screen.getByText("Backend OK")).toBeInTheDocument();
    expect(screen.getByText("Database OK")).toBeInTheDocument();
    expect(screen.getByText("Railway DNS OK")).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Push subscriptions:") && content.includes("3"))).toBeInTheDocument();
    expect(screen.getByText("Stato agente")).toBeInTheDocument();
  });
});

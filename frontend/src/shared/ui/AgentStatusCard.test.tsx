import { render, screen } from "@testing-library/react";

import { AgentStatusCard } from "./AgentStatusCard";

describe("AgentStatusCard", () => {
  it("renders a green online state", () => {
    render(
      <AgentStatusCard
        status={{
          agent_id: "agent-1",
          online: true,
          health_color: "green",
          last_heartbeat: "2026-06-18T08:00:00Z",
          last_station_update: "2026-06-18T08:00:30Z",
          last_session_import: "2026-06-18T07:55:00Z",
          heartbeat_count: 10,
          polling_count: 20,
          import_count: 2,
          retry_count: 1,
          failure_count: 0,
        }}
      />,
    );

    expect(screen.getByText("Agente online")).toBeInTheDocument();
    expect(screen.getByText("Operativo")).toBeInTheDocument();
    expect(screen.getByText("agent-1")).toBeInTheDocument();
    expect(screen.getByText("Retry count:")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders yellow and red severity labels", () => {
    const { rerender } = render(
      <AgentStatusCard
        status={{
          agent_id: "agent-1",
          online: true,
          health_color: "yellow",
          last_heartbeat: "2026-06-18T08:00:00Z",
          last_station_update: "2026-06-18T08:00:30Z",
          last_session_import: "2026-06-18T07:55:00Z",
          heartbeat_count: 10,
          polling_count: 20,
          import_count: 2,
          retry_count: 3,
          failure_count: 1,
        }}
      />,
    );

    expect(screen.getByText("Attenzione")).toBeInTheDocument();

    rerender(
      <AgentStatusCard
        status={{
          agent_id: "agent-1",
          online: false,
          health_color: "red",
          last_heartbeat: "2026-06-18T08:00:00Z",
          last_station_update: "2026-06-18T08:00:30Z",
          last_session_import: "2026-06-18T07:55:00Z",
          heartbeat_count: 10,
          polling_count: 20,
          import_count: 2,
          retry_count: 3,
          failure_count: 4,
        }}
      />,
    );

    expect(screen.getByText("Agente offline")).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
});

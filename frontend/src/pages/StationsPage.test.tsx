import { render, screen, waitFor } from "@testing-library/react";

import StationsPage from "./StationsPage";

const mocks = vi.hoisted(() => ({
  stations: vi.fn(),
  stationsOccupancy: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    stations: mocks.stations,
    stationsOccupancy: mocks.stationsOccupancy,
  },
}));

describe("StationsPage", () => {
  beforeEach(() => {
    mocks.stations.mockResolvedValue({
      items: [
        {
          id: 1,
          host: "192.168.1.200",
          vendor: "legrand_greenup",
          name: "Garage A",
          created_at: "2026-06-19T08:00:00Z",
          updated_at: "2026-06-19T08:35:00Z",
          session_count: 0,
          total_energy_wh: 0,
          latest_session: null,
          status: "available",
          status_source: "agent",
          last_sync_at: "2026-06-19T08:35:00Z",
          last_seen_at: "2026-06-19T08:35:00Z",
          last_poll_at: "2026-06-19T08:35:00Z",
          connector_status: "available",
          charging_state: "ready",
          status_is_fresh: true,
          active_session: false,
          active_session_source: "last_sync",
        },
      ],
      pagination: {
        total: 1,
        limit: 20,
        offset: 0,
      },
    });
    mocks.stationsOccupancy.mockRejectedValue(new Error("occupancy failed"));
  });

  it("falls back to fresh agent station status when occupancy fetch fails", async () => {
    render(<StationsPage />);

    await waitFor(() => expect(mocks.stations).toHaveBeenCalled());
    expect(await screen.findByText("Garage A")).toBeInTheDocument();
    expect(screen.getByText(/Free/)).toBeInTheDocument();
    expect(screen.queryByText(/Unavailable/)).not.toBeInTheDocument();
  });
});

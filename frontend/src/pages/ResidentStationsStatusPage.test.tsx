import { render, screen, waitFor } from "@testing-library/react";

import ResidentStationsStatusPage from "./ResidentStationsStatusPage";

const mocks = vi.hoisted(() => ({
  residentStationsStatus: vi.fn(),
  residentStationsOccupancy: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    residentStationsStatus: mocks.residentStationsStatus,
    residentStationsOccupancy: mocks.residentStationsOccupancy,
  },
}));

describe("ResidentStationsStatusPage", () => {
  beforeEach(() => {
    mocks.residentStationsStatus.mockResolvedValue({
      items: [
        {
          id: 1,
          name: "Garage A",
          known_status: "available",
          status_source: "agent",
          last_sync_at: "2026-06-19T08:35:00Z",
          last_seen_at: "2026-06-19T08:35:00Z",
          last_poll_at: "2026-06-19T08:35:00Z",
          connector_status: "available",
          charging_state: "ready",
          status_is_fresh: true,
          last_charge: null,
        },
      ],
    });
    mocks.residentStationsOccupancy.mockResolvedValue({
      items: [
        {
          station_id: 1,
          computed_status: "unavailable",
          last_checked_at: "2026-06-19T08:35:05Z",
          source: "live",
        },
      ],
    });
  });

  it("keeps a fresh known agent available state when occupancy returns unavailable from live fallback", async () => {
    render(<ResidentStationsStatusPage />);

    await waitFor(() => expect(mocks.residentStationsStatus).toHaveBeenCalled());
    await waitFor(() => expect(mocks.residentStationsOccupancy).toHaveBeenCalled());
    expect(screen.getByText("Garage A")).toBeInTheDocument();
    expect(screen.getByText(/FREE/)).toBeInTheDocument();
    expect(screen.queryByText(/UNAVAILABLE/)).not.toBeInTheDocument();
  });
});

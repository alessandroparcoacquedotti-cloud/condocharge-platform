import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ResidentStationsStatusPage from "./ResidentStationsStatusPage";

const mocks = vi.hoisted(() => ({
  residentStationsStatus: vi.fn(),
  residentStationsOccupancy: vi.fn(),
  residentQueueStatus: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    residentStationsStatus: mocks.residentStationsStatus,
    residentStationsOccupancy: mocks.residentStationsOccupancy,
    residentQueueStatus: mocks.residentQueueStatus,
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
    mocks.residentQueueStatus.mockResolvedValue({
      queue_enabled: true,
      in_queue: false,
      position: null,
      joined_at: null,
      active_entry_id: null,
      status: null,
    });
  });

  it("keeps a fresh known agent available state when occupancy returns unavailable from live fallback", async () => {
    render(
      <MemoryRouter initialEntries={["/resident/stato-colonnine"]}>
        <Routes>
          <Route path="/resident/stato-colonnine" element={<ResidentStationsStatusPage />} />
          <Route path="/resident/stato-colonnine/:stationId" element={<ResidentStationsStatusPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.residentStationsStatus).toHaveBeenCalled());
    await waitFor(() => expect(mocks.residentStationsOccupancy).toHaveBeenCalled());
    await waitFor(() => expect(mocks.residentQueueStatus).toHaveBeenCalled());
    expect(screen.getByText("Garage A")).toBeInTheDocument();
    expect(screen.getAllByText("Libera").length).toBeGreaterThan(0);
    expect(screen.queryByText("Non disponibile")).not.toBeInTheDocument();
    expect(screen.getByText("Le notifiche di disponibilita vengono inviate agli utenti in coda.")).toBeInTheDocument();
  });

  it("shows station details on the dedicated detail route", async () => {
    mocks.residentStationsStatus.mockResolvedValue({
      items: [
        {
          id: 1,
          name: "Garage A",
          known_status: "busy",
          status_source: "agent",
          last_sync_at: "2026-06-19T08:35:00Z",
          last_seen_at: "2026-06-19T08:35:00Z",
          last_poll_at: "2026-06-19T08:35:00Z",
          connector_status: "occupied",
          charging_state: "charging",
          status_is_fresh: true,
          last_charge: {
            end_time: "2026-06-19T08:30:00Z",
            energy_wh: 12345,
            total_minutes: 42,
          },
        },
      ],
    });

    mocks.residentStationsOccupancy.mockResolvedValue({
      items: [
        {
          station_id: 1,
          computed_status: "busy",
          last_checked_at: "2026-06-19T08:35:05Z",
          source: "agent",
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/resident/stato-colonnine/1"]}>
        <Routes>
          <Route path="/resident/stato-colonnine" element={<ResidentStationsStatusPage />} />
          <Route path="/resident/stato-colonnine/:stationId" element={<ResidentStationsStatusPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Ultima sessione")).toBeInTheDocument());
    expect(screen.getByText("Dettagli tecnici")).toBeInTheDocument();
    expect(screen.getByText("42 min")).toBeInTheDocument();
    expect(screen.getByText("occupied")).toBeInTheDocument();
    expect(screen.getByText("charging")).toBeInTheDocument();
  });
});

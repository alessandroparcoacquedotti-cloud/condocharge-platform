import { render, screen, waitFor } from "@testing-library/react";

import { ResidentQueueCard } from "./ResidentQueueCard";

const mocks = vi.hoisted(() => ({
  residentQueueStatus: vi.fn(),
  joinResidentQueue: vi.fn(),
  leaveResidentQueue: vi.fn(),
}));

vi.mock("../api/endpoints", () => ({
  endpoints: {
    residentQueueStatus: mocks.residentQueueStatus,
    joinResidentQueue: mocks.joinResidentQueue,
    leaveResidentQueue: mocks.leaveResidentQueue,
  },
}));

describe("ResidentQueueCard", () => {
  beforeEach(() => {
    mocks.residentQueueStatus.mockResolvedValue({
      queue_enabled: false,
      in_queue: false,
      position: null,
      joined_at: null,
      active_entry_id: null,
      status: null,
    });
    mocks.joinResidentQueue.mockResolvedValue({});
    mocks.leaveResidentQueue.mockResolvedValue({});
  });

  it("renders resident queue status without showing any roster", async () => {
    render(<ResidentQueueCard />);

    await waitFor(() => expect(mocks.residentQueueStatus).toHaveBeenCalled());
    expect(screen.getByText("Coda di attesa")).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Coda abilitata:"))).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("In coda:"))).toBeInTheDocument();
    expect(screen.getByText("Visualizzi solo la tua posizione personale. La lista dei condomini in coda non viene mostrata.")).toBeInTheDocument();
  });
});

import { render, screen, waitFor } from "@testing-library/react";

import { AdminQueueSettingsCard } from "./AdminQueueSettingsCard";

const mocks = vi.hoisted(() => ({
  adminQueueSettings: vi.fn(),
  updateAdminQueueSettings: vi.fn(),
}));

vi.mock("../api/endpoints", () => ({
  endpoints: {
    adminQueueSettings: mocks.adminQueueSettings,
    updateAdminQueueSettings: mocks.updateAdminQueueSettings,
  },
}));

describe("AdminQueueSettingsCard", () => {
  beforeEach(() => {
    mocks.adminQueueSettings.mockResolvedValue({
      queue_enabled: false,
      waiting_count: 0,
      updated_at: "2026-06-20T08:00:00Z",
    });
    mocks.updateAdminQueueSettings.mockResolvedValue({
      queue_enabled: true,
      waiting_count: 0,
      updated_at: "2026-06-20T08:05:00Z",
    });
  });

  it("renders queue foundation settings with disabled-by-default guidance", async () => {
    render(<AdminQueueSettingsCard />);

    await waitFor(() => expect(mocks.adminQueueSettings).toHaveBeenCalled());
    expect(screen.getByText("Coda di attesa")).toBeInTheDocument();
    expect(screen.getByText("La coda e disattivata per default fino a validazione operativa.")).toBeInTheDocument();
    expect(screen.getByText("Abilita coda condominiale")).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Condomini in attesa: 0"))).toBeInTheDocument();
  });
});

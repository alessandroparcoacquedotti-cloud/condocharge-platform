import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";

import ResidentProfilePage from "./ResidentProfilePage";

const mocks = vi.hoisted(() => ({
  residentProfile: vi.fn(),
  updateResidentProfile: vi.fn(),
  updateResidentNotificationPreferences: vi.fn(),
  issueResidentTelegramLink: vi.fn(),
  unlinkResidentTelegram: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    residentProfile: mocks.residentProfile,
    updateResidentProfile: mocks.updateResidentProfile,
    updateResidentNotificationPreferences: mocks.updateResidentNotificationPreferences,
    issueResidentTelegramLink: mocks.issueResidentTelegramLink,
    unlinkResidentTelegram: mocks.unlinkResidentTelegram,
  },
}));

describe("ResidentProfilePage", () => {
  beforeEach(() => {
    mocks.residentProfile.mockResolvedValue({
      username: "resident",
      first_name: "Alice",
      last_name: "Rossi",
      apartment_or_unit: "A-12",
      email: "alice@example.com",
      phone_number: "123",
      linked_cards: [],
      notification_preferences: {
        charging_completed: true,
        station_available: true,
        station_back_online: false,
        agent_offline: true,
        agent_recovered: true,
      },
      telegram: {
        linked: true,
        chat_id: "555",
        telegram_username: "alice_bot",
        linked_at: "2026-06-19T09:00:00Z",
      },
    });
    mocks.updateResidentProfile.mockResolvedValue({});
    mocks.updateResidentNotificationPreferences.mockResolvedValue({});
    mocks.issueResidentTelegramLink.mockResolvedValue({
      expires_at: "2026-06-19T10:00:00Z",
      deep_link_url: "https://t.me/CondoChargeBot?start=abc",
      bot_username: "CondoChargeBot",
    });
    mocks.unlinkResidentTelegram.mockResolvedValue({
      linked: false,
      chat_id: null,
      telegram_username: null,
      linked_at: null,
    });
  });

  it("renders Telegram status and new agent preference toggles", async () => {
    render(
      <MemoryRouter>
        <ResidentProfilePage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.residentProfile).toHaveBeenCalled());
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText("Collegato")).toBeInTheDocument();
    expect(screen.getByText("Agente offline")).toBeInTheDocument();
    expect(screen.getByText("Agente ripristinato")).toBeInTheDocument();
    expect(screen.getByText("Genera link Telegram")).toBeInTheDocument();
  });
});

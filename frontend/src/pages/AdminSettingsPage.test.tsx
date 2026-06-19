import { render, screen, waitFor } from "@testing-library/react";

import AdminSettingsPage from "./AdminSettingsPage";

const mocks = vi.hoisted(() => ({
  adminSettings: vi.fn(),
  adminEmailHealth: vi.fn(),
  adminTelegramStatus: vi.fn(),
  updateAdminSettings: vi.fn(),
  testAdminEmail: vi.fn(),
  testAdminTelegram: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    adminSettings: mocks.adminSettings,
    adminEmailHealth: mocks.adminEmailHealth,
    adminTelegramStatus: mocks.adminTelegramStatus,
    updateAdminSettings: mocks.updateAdminSettings,
    testAdminEmail: mocks.testAdminEmail,
    testAdminTelegram: mocks.testAdminTelegram,
  },
}));

describe("AdminSettingsPage", () => {
  beforeEach(() => {
    mocks.adminSettings.mockResolvedValue({
      energy_price_eur_per_kwh: 0.3,
      telegram_station_available_enabled: true,
      telegram_charging_completed_enabled: true,
      telegram_agent_offline_enabled: true,
      telegram_agent_recovered_enabled: true,
    });
    mocks.adminEmailHealth.mockResolvedValue({
      status: "disabled",
      host: null,
      port: null,
      use_tls: null,
      message: "Email disabled",
    });
    mocks.adminTelegramStatus.mockResolvedValue({
      status: "ok",
      configured: true,
      bot_username: "CondoChargeBot",
      webhook_path: "/api/v1/telegram/webhook",
      message: null,
    });
    mocks.updateAdminSettings.mockResolvedValue({
      energy_price_eur_per_kwh: 0.3,
      telegram_station_available_enabled: true,
      telegram_charging_completed_enabled: true,
      telegram_agent_offline_enabled: true,
      telegram_agent_recovered_enabled: true,
    });
    mocks.testAdminEmail.mockResolvedValue({});
    mocks.testAdminTelegram.mockResolvedValue({
      chat_id: "123",
      delivery_status: "preview",
      telegram_enabled: false,
      message_preview: "preview",
      provider_message_id: null,
    });
  });

  it("renders Telegram bot status and notification toggles", async () => {
    render(<AdminSettingsPage />);

    await waitFor(() => expect(mocks.adminSettings).toHaveBeenCalled());
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText("Telegram: colonnina disponibile")).toBeInTheDocument();
    expect(screen.getByText("Telegram: agente offline")).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Bot:") && content.includes("CondoChargeBot"))).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Webhook:") && content.includes("/api/v1/telegram/webhook"))).toBeInTheDocument();
  });
});

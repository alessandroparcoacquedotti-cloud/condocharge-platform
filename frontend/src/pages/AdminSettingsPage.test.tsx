import { render, screen, waitFor } from "@testing-library/react";

import AdminSettingsPage from "./AdminSettingsPage";

const mocks = vi.hoisted(() => ({
  adminQueueSettings: vi.fn(),
  adminSettings: vi.fn(),
  adminResidents: vi.fn(),
  adminEmailHealth: vi.fn(),
  adminTelegramStatus: vi.fn(),
  updateAdminQueueSettings: vi.fn(),
  updateAdminSettings: vi.fn(),
  testAdminEmail: vi.fn(),
  testAdminTelegram: vi.fn(),
  simulateAdminTelegram: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    adminQueueSettings: mocks.adminQueueSettings,
    adminSettings: mocks.adminSettings,
    adminResidents: mocks.adminResidents,
    adminEmailHealth: mocks.adminEmailHealth,
    adminTelegramStatus: mocks.adminTelegramStatus,
    updateAdminQueueSettings: mocks.updateAdminQueueSettings,
    updateAdminSettings: mocks.updateAdminSettings,
    testAdminEmail: mocks.testAdminEmail,
    testAdminTelegram: mocks.testAdminTelegram,
    simulateAdminTelegram: mocks.simulateAdminTelegram,
  },
}));

describe("AdminSettingsPage", () => {
  beforeEach(() => {
    mocks.adminSettings.mockResolvedValue({
      energy_price_eur_per_kwh: 0.3,
      telegram_station_available_enabled: true,
      telegram_station_busy_enabled: false,
      telegram_station_back_online_enabled: false,
      telegram_charging_completed_enabled: true,
      telegram_agent_offline_enabled: true,
      telegram_agent_recovered_enabled: true,
    });
    mocks.adminQueueSettings.mockResolvedValue({
      queue_enabled: false,
      waiting_count: 0,
      updated_at: "2026-06-20T08:00:00Z",
    });
    mocks.adminResidents.mockResolvedValue([
      {
        app_user_id: 12,
        username: "resident",
        first_name: null,
        last_name: null,
        apartment_or_unit: null,
        email: null,
        phone_number: null,
        role: "resident",
        is_active: true,
        must_change_password: false,
        last_login_at: null,
        invitation_status: "accepted",
        invitation_sent_at: null,
        invitation_expires_at: null,
        linked_cards: [],
        total_energy_wh: 0,
        total_energy_kwh: 0,
        estimated_cost_eur: 0,
      },
    ]);
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
      telegram_station_busy_enabled: false,
      telegram_station_back_online_enabled: false,
      telegram_charging_completed_enabled: true,
      telegram_agent_offline_enabled: true,
      telegram_agent_recovered_enabled: true,
    });
    mocks.updateAdminQueueSettings.mockResolvedValue({
      queue_enabled: true,
      waiting_count: 0,
      updated_at: "2026-06-20T08:05:00Z",
    });
    mocks.testAdminEmail.mockResolvedValue({});
    mocks.testAdminTelegram.mockResolvedValue({
      chat_id: "123",
      delivery_status: "preview",
      telegram_enabled: false,
      message_preview: "preview",
      provider_message_id: null,
    });
    mocks.simulateAdminTelegram.mockResolvedValue({
      resident_app_user_id: 12,
      resident_username: "resident",
      notification_type: "station_available",
      delivery_status: "preview",
      telegram_enabled: false,
      provider_message_id: null,
      audit_id: 99,
      audit_status: "preview",
      message_preview: "preview",
    });
  });

  it("renders queue settings, Telegram bot status, notification toggles, and simulator", async () => {
    render(<AdminSettingsPage />);

    await waitFor(() => expect(mocks.adminSettings).toHaveBeenCalled());
    expect(screen.getByText("Abilita coda condominiale")).toBeInTheDocument();
    expect(screen.getByText("Telegram")).toBeInTheDocument();
    expect(screen.getByText("Telegram: colonnina disponibile")).toBeInTheDocument();
    expect(screen.getByText("Telegram: colonnina occupata")).toBeInTheDocument();
    expect(screen.getByText("Telegram: colonnina tornata online")).toBeInTheDocument();
    expect(screen.getByText("Telegram: agente offline")).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Bot:") && content.includes("CondoChargeBot"))).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("Webhook:") && content.includes("/api/v1/telegram/webhook"))).toBeInTheDocument();
    expect(screen.getByText("Telegram Testing")).toBeInTheDocument();
    expect(screen.getByText("Test Colonnina Disponibile")).toBeInTheDocument();
  });
});

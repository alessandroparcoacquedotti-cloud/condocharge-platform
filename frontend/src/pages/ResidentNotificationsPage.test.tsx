import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ResidentNotificationsPage from "./ResidentNotificationsPage";

const mocks = vi.hoisted(() => ({
  residentNotificationPreferences: vi.fn(),
  updateResidentNotificationPreferences: vi.fn(),
  residentProfile: vi.fn(),
  getNotificationPermissionState: vi.fn(),
  syncExistingSubscription: vi.fn(),
  resolveBrowserPushState: vi.fn(),
  requestNotificationPermission: vi.fn(),
  subscribeToPush: vi.fn(),
  unsubscribeFromPush: vi.fn(),
  collectPushDiagnosticsSnapshot: vi.fn(),
}));

vi.mock("../shared/api/endpoints", () => ({
  endpoints: {
    residentNotificationPreferences: mocks.residentNotificationPreferences,
    updateResidentNotificationPreferences: mocks.updateResidentNotificationPreferences,
    residentProfile: mocks.residentProfile,
  },
}));

vi.mock("../shared/notifications/pushService", () => ({
  getNotificationPermissionState: mocks.getNotificationPermissionState,
  syncExistingSubscription: mocks.syncExistingSubscription,
  resolveBrowserPushState: mocks.resolveBrowserPushState,
  requestNotificationPermission: mocks.requestNotificationPermission,
  subscribeToPush: mocks.subscribeToPush,
  unsubscribeFromPush: mocks.unsubscribeFromPush,
  collectPushDiagnosticsSnapshot: mocks.collectPushDiagnosticsSnapshot,
}));

describe("ResidentNotificationsPage", () => {
  beforeEach(() => {
    mocks.residentNotificationPreferences.mockResolvedValue({
      charging_completed: true,
      station_available: true,
      station_busy: true,
      station_back_online: true,
      agent_offline: true,
      agent_recovered: true,
    });
    mocks.updateResidentNotificationPreferences.mockResolvedValue({});
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
        station_busy: true,
        station_back_online: true,
        agent_offline: true,
        agent_recovered: true,
      },
      push: { subscribed: true, active_subscriptions: 1, web_push_enabled: true },
      telegram: { linked: false, chat_id: null, telegram_username: null, linked_at: null },
    });
    mocks.getNotificationPermissionState.mockReturnValue("granted");
    mocks.syncExistingSubscription.mockResolvedValue(true);
    mocks.resolveBrowserPushState.mockResolvedValue("active");
    mocks.requestNotificationPermission.mockResolvedValue("granted");
    mocks.subscribeToPush.mockResolvedValue(null);
    mocks.unsubscribeFromPush.mockResolvedValue(true);
    mocks.collectPushDiagnosticsSnapshot.mockResolvedValue({
      vapidPublicKeyRuntimePresent: true,
      vapidPublicKeyRuntimePrefix: "BPEpdFZv…",
      isSecureContext: true,
      locationHref: "https://example.com",
      userAgent: "UA",
      pushSupported: true,
      notificationPermissionState: "granted",
      serviceWorkerSupported: true,
      serviceWorkerController: true,
      serviceWorkerReadyResolved: true,
      serviceWorkerRegistrationPresent: true,
      serviceWorkerScope: "https://example.com/",
      pushSubscriptionPresent: true,
    });
  });

  it("shows push controls and explanatory copy on Notifiche page", async () => {
    render(
      <MemoryRouter>
        <ResidentNotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.residentNotificationPreferences).toHaveBeenCalled());
    await waitFor(() => expect(mocks.residentProfile).toHaveBeenCalled());
    expect(screen.getByText("Notifiche")).toBeInTheDocument();
    expect(screen.getByText("Notifiche push")).toBeInTheDocument();
    expect(screen.getByText("Le notifiche app arrivano anche quando Condo Charge e chiusa.")).toBeInTheDocument();
    expect(screen.getByText("Attiva notifiche")).toBeInTheDocument();
    expect(screen.getByText("Disattiva notifiche")).toBeInTheDocument();
    expect(screen.getByText("Diagnostica push")).toBeInTheDocument();
  });
});

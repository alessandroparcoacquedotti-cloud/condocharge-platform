import { endpoints } from "../api/endpoints";

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY;

export type BrowserPushState = "active" | "disabled" | "unsupported";

// Convert VAPID public key from base64 to ArrayBuffer for use in subscription
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!("Notification" in window)) {
    return "denied";
  }
  return await Notification.requestPermission();
}

export function isPushSupported(): boolean {
  return "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

export function getNotificationPermissionState(): NotificationPermission | "unsupported" {
  if (!("Notification" in window)) {
    return "unsupported";
  }
  return Notification.permission;
}

export async function getPushSubscription(): Promise<PushSubscription | null> {
  if (!isPushSupported()) {
    return null;
  }
  const registration = await navigator.serviceWorker.ready;
  return await registration.pushManager.getSubscription();
}

function subscriptionPayload(subscription: PushSubscription): { endpoint: string; keys: { p256dh: string; auth: string } } {
  const json = subscription.toJSON();
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!json.endpoint || !p256dh || !auth) {
    throw new Error("Sottoscrizione push non valida");
  }
  return {
    endpoint: json.endpoint,
    keys: {
      p256dh,
      auth,
    },
  };
}

export async function subscribeToPush(): Promise<PushSubscription | null> {
  if (!VAPID_PUBLIC_KEY) {
    throw new Error("Chiave VAPID pubblica non configurata");
  }
  if (!isPushSupported()) {
    throw new Error("Notifiche push non supportate");
  }
  const registration = await navigator.serviceWorker.ready;
  const existingSubscription = await registration.pushManager.getSubscription();
  if (existingSubscription) {
    await endpoints.pushSubscribe(subscriptionPayload(existingSubscription));
    return existingSubscription;
  }
  const applicationServerKey = urlBase64ToUint8Array(VAPID_PUBLIC_KEY) as unknown as BufferSource;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey,
  });
  await endpoints.pushSubscribe(subscriptionPayload(subscription));
  return subscription;
}

export async function unsubscribeFromPush(): Promise<boolean> {
  const subscription = await getPushSubscription();
  if (!subscription) {
    return false;
  }
  await endpoints.pushUnsubscribe(subscriptionPayload(subscription));
  return await subscription.unsubscribe();
}

export async function syncExistingSubscription(): Promise<boolean> {
  const subscription = await getPushSubscription();
  if (!subscription) {
    return false;
  }
  await endpoints.pushSubscribe(subscriptionPayload(subscription));
  return true;
}

export async function sendPushTest(): Promise<{ delivery_status: string; delivered_count: number }> {
  const response = await endpoints.pushTest();
  return {
    delivery_status: response.delivery_status,
    delivered_count: response.delivered_count,
  };
}

export async function resolveBrowserPushState(serverSubscribed: boolean): Promise<BrowserPushState> {
  if (!isPushSupported()) {
    return "unsupported";
  }
  const subscription = await getPushSubscription();
  return subscription || serverSubscribed ? "active" : "disabled";
}

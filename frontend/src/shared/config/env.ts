const DEFAULT_PROD_API_BASE_URL = "https://condocharge-platform-production.up.railway.app";

function normalizeString(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.trim();
}

function resolveApiBaseUrl(): string {
  if (import.meta.env.DEV) {
    return normalizeString(import.meta.env.VITE_API_BASE_URL);
  }
  return DEFAULT_PROD_API_BASE_URL;
}

export const env = {
  apiBaseUrl: resolveApiBaseUrl(),
  defaultCondominiumName: import.meta.env.VITE_DEFAULT_CONDOMINIUM_NAME ?? "",
} as const;

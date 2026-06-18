const DEFAULT_PROD_API_BASE_URL = "https://condocharge-prod.up.railway.app";

function normalizeString(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.trim();
}

function resolveApiBaseUrl(): string {
  const configured = normalizeString(import.meta.env.VITE_API_BASE_URL);
  if (configured) return configured;
  return DEFAULT_PROD_API_BASE_URL;
}

export const env = {
  apiBaseUrl: resolveApiBaseUrl(),
  defaultCondominiumName: import.meta.env.VITE_DEFAULT_CONDOMINIUM_NAME ?? "",
} as const;

const DEFAULT_PROD_API_BASE_URL = "https://condocharge-platform-production.up.railway.app";
const DEFAULT_DEMO_CONDOMINIUM_NAME = "Riverview Residences";

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
  defaultCondominiumName: normalizeString(import.meta.env.VITE_DEFAULT_CONDOMINIUM_NAME) || DEFAULT_DEMO_CONDOMINIUM_NAME,
} as const;

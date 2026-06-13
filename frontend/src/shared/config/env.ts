export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  defaultCondominiumName: import.meta.env.VITE_DEFAULT_CONDOMINIUM_NAME ?? "",
} as const;

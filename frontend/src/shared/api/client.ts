import { env } from "../config/env";

export type ApiClientOptions = {
  baseUrl?: string;
  timeoutMs?: number;
};

export type ApiError = {
  status: number;
  message: string;
  details?: unknown;
};

const TOKEN_STORAGE_KEY = "condocharge_access_token";
const DEFAULT_TIMEOUT_MS = 15000;

function joinUrl(baseUrl: string, path: string) {
  const trimmedBase = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
}

function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? env.apiBaseUrl;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  function withTimeout(init: RequestInit = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    const signal = init.signal ? (init.signal as AbortSignal) : controller.signal;
    return { init: { ...init, signal }, cleanup: () => window.clearTimeout(timer) };
  }

  return {
    async get(path: string, init: RequestInit = {}) {
      const token = getStoredToken();
      const wrapped = withTimeout(init);
      let res: Response;
      try {
        res = await fetch(joinUrl(baseUrl, path), {
          ...wrapped.init,
          method: "GET",
          cache: "no-store",
          headers: {
            Accept: "application/json",
            "Cache-Control": "no-store",
            ...(init.headers ?? {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
      } finally {
        wrapped.cleanup();
      }
      if (!res.ok) {
        let details: unknown = undefined;
        try {
          details = await res.json();
        } catch {
          details = await res.text().catch(() => undefined);
        }
        const error: ApiError = {
          status: res.status,
          message: `Request failed: ${res.status} ${res.statusText}`,
          details,
        };
        throw error;
      }
      return res;
    },
    async post(path: string, init: RequestInit = {}) {
      const token = getStoredToken();
      const wrapped = withTimeout(init);
      const finalUrl = joinUrl(baseUrl, path);
      const requestOptions: RequestInit = {
        ...wrapped.init,
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Cache-Control": "no-store",
          ...(init.headers ?? {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      };
      let res: Response;
      try {
        console.log("FETCH_URL", finalUrl);
        console.log("FETCH_OPTIONS", requestOptions);
        res = await fetch(finalUrl, requestOptions);
      } catch (error) {
        console.error("FETCH_FAILURE", {
          raw: error,
          name: error instanceof Error ? error.name : undefined,
          message: error instanceof Error ? error.message : String(error),
          onLine: navigator.onLine,
        });
        throw error;
      } finally {
        wrapped.cleanup();
      }
      if (!res.ok) {
        let details: unknown = undefined;
        try {
          details = await res.json();
        } catch {
          details = await res.text().catch(() => undefined);
        }
        const error: ApiError = {
          status: res.status,
          message: `Request failed: ${res.status} ${res.statusText}`,
          details,
        };
        throw error;
      }
      return res;
    },
    async patch(path: string, init: RequestInit = {}) {
      const token = getStoredToken();
      const wrapped = withTimeout(init);
      let res: Response;
      try {
        res = await fetch(joinUrl(baseUrl, path), {
          ...wrapped.init,
          method: "PATCH",
          cache: "no-store",
          headers: {
            Accept: "application/json",
            "Cache-Control": "no-store",
            ...(init.headers ?? {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
      } finally {
        wrapped.cleanup();
      }
      if (!res.ok) {
        let details: unknown = undefined;
        try {
          details = await res.json();
        } catch {
          details = await res.text().catch(() => undefined);
        }
        const error: ApiError = {
          status: res.status,
          message: `Request failed: ${res.status} ${res.statusText}`,
          details,
        };
        throw error;
      }
      return res;
    },
    async put(path: string, init: RequestInit = {}) {
      const token = getStoredToken();
      const wrapped = withTimeout(init);
      let res: Response;
      try {
        res = await fetch(joinUrl(baseUrl, path), {
          ...wrapped.init,
          method: "PUT",
          cache: "no-store",
          headers: {
            Accept: "application/json",
            "Cache-Control": "no-store",
            ...(init.headers ?? {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
      } finally {
        wrapped.cleanup();
      }
      if (!res.ok) {
        let details: unknown = undefined;
        try {
          details = await res.json();
        } catch {
          details = await res.text().catch(() => undefined);
        }
        const error: ApiError = {
          status: res.status,
          message: `Request failed: ${res.status} ${res.statusText}`,
          details,
        };
        throw error;
      }
      return res;
    },
    async delete(path: string, init: RequestInit = {}) {
      const token = getStoredToken();
      const wrapped = withTimeout(init);
      let res: Response;
      try {
        res = await fetch(joinUrl(baseUrl, path), {
          ...wrapped.init,
          method: "DELETE",
          cache: "no-store",
          headers: {
            Accept: "application/json",
            "Cache-Control": "no-store",
            ...(init.headers ?? {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
      } finally {
        wrapped.cleanup();
      }
      if (!res.ok) {
        let details: unknown = undefined;
        try {
          details = await res.json();
        } catch {
          details = await res.text().catch(() => undefined);
        }
        const error: ApiError = {
          status: res.status,
          message: `Request failed: ${res.status} ${res.statusText}`,
          details,
        };
        throw error;
      }
      return res;
    },
    async getJson<T>(path: string, init: RequestInit = {}) {
      const res = await this.get(path, init);
      return (await res.json()) as T;
    },
    async postJson<T>(path: string, body: unknown, init: RequestInit = {}) {
      const res = await this.post(path, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...(init.headers ?? {}),
        },
        body: JSON.stringify(body),
      });
      return (await res.json()) as T;
    },
    async patchJson<T>(path: string, body: unknown, init: RequestInit = {}) {
      const res = await this.patch(path, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...(init.headers ?? {}),
        },
        body: JSON.stringify(body),
      });
      return (await res.json()) as T;
    },
    async putJson<T>(path: string, body: unknown, init: RequestInit = {}) {
      const res = await this.put(path, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...(init.headers ?? {}),
        },
        body: JSON.stringify(body),
      });
      return (await res.json()) as T;
    },
    async deleteJson<T>(path: string, init: RequestInit = {}) {
      const res = await this.delete(path, init);
      return (await res.json()) as T;
    },
  };
}

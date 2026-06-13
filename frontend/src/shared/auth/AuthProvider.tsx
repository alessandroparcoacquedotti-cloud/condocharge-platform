import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { AppUserResponse } from "../api/types";

const TOKEN_STORAGE_KEY = "condocharge_access_token";

type AuthState = {
  user: AppUserResponse | null;
  isLoading: boolean;
  login: (params: { username: string; password: string; condominium?: string }) => Promise<void>;
  logout: () => void;
  updateUser: (next: AppUserResponse) => void;
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    return;
  }
}

export function AuthProvider(props: { children: ReactNode }) {
  const [user, setUser] = useState<AppUserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    endpoints
      .me()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setIsLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setToken(null);
        setUser(null);
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      isLoading,
      async login(params) {
        const res = await endpoints.login(params);
        setToken(res.token.access_token);
        setUser(res.user);
      },
      logout() {
        setToken(null);
        setUser(null);
      },
      updateUser(next) {
        setUser(next);
      },
      async refreshMe() {
        const me = await endpoints.me();
        setUser(me);
      },
    }),
    [user, isLoading],
  );

  return <AuthContext.Provider value={value}>{props.children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
}

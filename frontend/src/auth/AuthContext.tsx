import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  authApi,
  getStoredToken,
  setStoredToken,
  userCanBuild,
  userHasTemplate,
  type AuthResult,
  type User,
} from "./api";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  isAuthenticated: boolean;
  canBuild: boolean;
  isOwner: boolean;
  login: (email: string, password: string) => Promise<AuthResult>;
  register: (email: string, password: string, name: string) => Promise<AuthResult>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  applyAuthResult: (res: AuthResult) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const applyAuthResult = useCallback((res: AuthResult) => {
    if (res.access_token && res.user) {
      setStoredToken(res.access_token);
      setUser(res.user);
    } else {
      setStoredToken(null);
      setUser(null);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      return;
    }
    try {
      const me = await authApi.me(token);
      setUser(me);
    } catch {
      setStoredToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await refreshUser();
      } finally {
        setLoading(false);
      }
    })();
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    applyAuthResult(res);
    return res;
  }, [applyAuthResult]);

  const register = useCallback(async (email: string, password: string, name: string) => {
    const res = await authApi.register(email, password, name);
    applyAuthResult(res);
    return res;
  }, [applyAuthResult]);

  const logout = useCallback(() => {
    setStoredToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user),
      canBuild: userCanBuild(user),
      isOwner: user?.role === "owner",
      login,
      register,
      logout,
      refreshUser,
      applyAuthResult,
    }),
    [user, loading, login, register, logout, refreshUser, applyAuthResult],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function getPostAuthPath(user: User | null, status?: AuthResult["status"]): string {
  if (status === "pending_access" || (user && !userCanBuild(user))) {
    return "/pending-access";
  }
  if (user && userCanBuild(user) && !userHasTemplate(user)) {
    return "/templates";
  }
  if (user && userCanBuild(user)) {
    return "/builder";
  }
  return "/auth";
}

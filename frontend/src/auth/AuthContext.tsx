import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  authApi,
  getStoredToken,
  SESSION_ENDED_EVENT,
  setStoredToken,
  userCanBuild,
  type AuthResult,
  type User,
} from "./api";

/** sessionStorage key: why the user was just signed out (shown once on the sign-in page). */
export const SESSION_NOTICE_KEY = "jobbot_session_notice";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  isAuthenticated: boolean;
  canBuild: boolean;
  isOwner: boolean;
  canManageApplications: boolean;
  canViewTeamApplications: boolean;
  login: (email: string, password: string) => Promise<AuthResult>;
  register: (email: string, password: string, name: string) => Promise<AuthResult>;
  verifyEmail: (token: string) => Promise<AuthResult>;
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

  // One browser per account: if this account signs in somewhere else, the server
  // rejects this browser's token. Drop to the sign-in page with an explanation.
  useEffect(() => {
    const onEnded = (e: Event) => {
      const message = (e as CustomEvent<string>).detail;
      try {
        sessionStorage.setItem(SESSION_NOTICE_KEY, message);
      } catch {
        /* storage unavailable — the redirect still happens */
      }
      setUser(null);
    };
    window.addEventListener(SESSION_ENDED_EVENT, onEnded);
    return () => window.removeEventListener(SESSION_ENDED_EVENT, onEnded);
  }, []);

  // Notice a replaced session promptly even when idle: re-check on focus and every minute.
  useEffect(() => {
    if (!user) return;
    const check = () => {
      if (getStoredToken()) void authApi.me().catch(() => {});
    };
    window.addEventListener("focus", check);
    const timer = window.setInterval(check, 60_000);
    return () => {
      window.removeEventListener("focus", check);
      window.clearInterval(timer);
    };
  }, [user]);

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

  const verifyEmail = useCallback(async (token: string) => {
    const res = await authApi.verifyEmail(token);
    applyAuthResult(res);
    return res;
  }, [applyAuthResult]);

  const logout = useCallback(() => {
    // End the session server-side too (best effort), then forget it locally.
    if (getStoredToken()) void authApi.logout().catch(() => {});
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
      canManageApplications: Boolean(user?.can_manage_applications),
      canViewTeamApplications: Boolean(user?.can_view_team_applications),
      login,
      register,
      verifyEmail,
      logout,
      refreshUser,
      applyAuthResult,
    }),
    [user, loading, login, register, verifyEmail, logout, refreshUser, applyAuthResult],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function getPostAuthPath(user: User | null, status?: AuthResult["status"]): string {
  if (status === "pending_verification" || (user && !user.email_verified)) {
    return "/auth/check-email";
  }
  if (status === "pending_access" || (user && user.email_verified && !userCanBuild(user))) {
    return "/pending-access";
  }
  if (user && userCanBuild(user)) {
    return "/builder";
  }
  return "/auth";
}

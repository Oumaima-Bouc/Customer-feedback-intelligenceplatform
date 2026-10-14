'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import { login as apiLogin, getMe, logout, getToken, clearToken } from './api';

interface AuthCtx {
  user: any | null;
  loading: boolean;
  error: string | null;
  mustChangePassword: boolean;
  login: (username: string, password: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  setMustChangePassword: (value: boolean) => void;
  doLogout: () => Promise<void>;
}

const AuthContext = createContext<AuthCtx>({
  user: null,
  loading: true,
  error: null,
  mustChangePassword: false,
  login: async () => {},
  refreshUser: async () => {},
  setMustChangePassword: () => {},
  doLogout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  // Load the current user from an existing token. Does NOT auto-login.
  const refreshUser = async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const me = await getMe();
      setUser(me);
      setMustChangePassword(!!me.password_change_required);
      setError(null);
    } catch (e: any) {
      // Invalid/expired token — clear it and fall back to the login screen.
      clearToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = async (username: string, password: string) => {
    setError(null);
    const result = await apiLogin(username, password); // throws on bad credentials
    setMustChangePassword(!!result.password_change_required);
    const me = await getMe();
    setUser(me);
  };

  const doLogout = async () => {
    try {
      await logout();
    } catch {
      // A failed server logout should not prevent local session cleanup.
    }
    clearToken();
    setUser(null);
    setMustChangePassword(false);
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  useEffect(() => {
    refreshUser();
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, loading, error, mustChangePassword, login, refreshUser, setMustChangePassword, doLogout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

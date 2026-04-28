import React, { createContext, useContext, useEffect, useState } from "react";
import type { AuthUser, LoginResponse } from "../types";

const AUTH_KEY = "pds360_token";
const USER_KEY = "pds360_user";

type AuthContextValue = {
  user:    AuthUser | null;
  token:   string | null;
  login:   (resp: LoginResponse) => void;
  logout:  () => void;
  isAuth:  boolean;
};

const AuthContext = createContext<AuthContextValue>({
  user: null, token: null,
  login: () => {}, logout: () => {},
  isAuth: false,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(AUTH_KEY));
  const [user,  setUser]  = useState<AuthUser | null>(() => {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  });

  const login = (resp: LoginResponse) => {
    localStorage.setItem(AUTH_KEY, resp.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(resp.user));
    setToken(resp.access_token);
    setUser(resp.user);
  };

  const logout = () => {
    localStorage.removeItem(AUTH_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuth: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export function getStoredToken(): string | null {
  return localStorage.getItem(AUTH_KEY);
}

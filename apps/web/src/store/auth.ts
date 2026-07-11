/**
 * Zustand auth store — access tokens in memory only (not localStorage).
 * Refresh tokens live in httpOnly cookies, handled server-side.
 */
import { create } from "zustand";

interface User { id: string; email: string; risk_tolerance: string; }

interface AuthState {
  accessToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  setToken: (token: string, user: User) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,
  setToken: (token, user) => set({ accessToken: token, user, isAuthenticated: true }),
  clearAuth: () => set({ accessToken: null, user: null, isAuthenticated: false }),
}));

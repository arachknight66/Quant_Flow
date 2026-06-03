// apps/web/src/store/auth.ts
/**
 * Zustand auth store.
 * Access tokens are stored in memory only (NOT localStorage).
 * Refresh tokens are in httpOnly cookies (handled by the browser automatically).
 *
 * Tradeoff: Refreshing the page loses the access token → silent refresh
 * via the refresh token cookie on every app load.
 */
import { create } from "zustand";

interface AuthState {
  accessToken: string | null;
  user: { id: string; email: string } | null;
  isAuthenticated: boolean;
  setToken: (token: string, user: { id: string; email: string }) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,

  setToken: (token, user) =>
    set({ accessToken: token, user, isAuthenticated: true }),

  logout: () => {
    set({ accessToken: null, user: null, isAuthenticated: false });
    // The httpOnly cookie is cleared server-side via DELETE /auth/logout
  },
}));
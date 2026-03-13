import { create } from 'zustand';

import type { User } from '@/types';
import { authSession } from '@/services/authSession';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  setAuthenticated: (isAuthenticated: boolean) => void;
  setLoading: (isLoading: boolean) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  setUser: (user) => set({ user }),
  setAuthenticated: (isAuthenticated) => set({ isAuthenticated }),
  setLoading: (isLoading) => set({ isLoading }),
  logout: () => {
    authSession.clear();
    set({ user: null, isAuthenticated: false });
  },
}));


import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../services/api';
import { User } from '../types';

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ ok: boolean; message?: string }>;
  register: (name: string, email: string, password: string) => Promise<{ ok: boolean; message?: string }>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const cached = await AsyncStorage.getItem('auth_user');
      if (cached) setUser(JSON.parse(cached));
      try {
        const res = await api.me();
        if (res.success && res.data?.user) {
          setUser(res.data.user);
          await AsyncStorage.setItem('auth_user', JSON.stringify(res.data.user));
        }
      } catch (_err) {
        // Ignore boot-time network failures and allow auth screen rendering.
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login: async (email, password) => {
        const res = await api.login(email, password);
        if (!res.success || !res.data?.user) return { ok: false, message: res.message || 'Dang nhap that bai' };
        setUser(res.data.user);
        await AsyncStorage.setItem('auth_user', JSON.stringify(res.data.user));
        return { ok: true, message: res.message };
      },
      register: async (name, email, password) => {
        const res = await api.register(name, email, password);
        if (!res.success || !res.data?.user) return { ok: false, message: res.message || 'Dang ky that bai' };
        setUser(res.data.user);
        await AsyncStorage.setItem('auth_user', JSON.stringify(res.data.user));
        return { ok: true, message: res.message };
      },
      logout: async () => {
        await api.logout();
        setUser(null);
        await AsyncStorage.removeItem('auth_user');
      },
    }),
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

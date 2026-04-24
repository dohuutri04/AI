import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

const THEME_KEY = 'app_theme_mode';

type ThemeMode = 'light' | 'dark';

type ThemeTokens = {
  mode: ThemeMode;
  bg: string;
  card: string;
  text: string;
  subtext: string;
  border: string;
  primary: string;
};

type ThemeContextValue = {
  theme: ThemeTokens;
  toggleTheme: () => Promise<void>;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function buildTheme(mode: ThemeMode): ThemeTokens {
  if (mode === 'dark') {
    return {
      mode,
      bg: '#020617',
      card: '#0f172a',
      text: '#e2e8f0',
      subtext: '#94a3b8',
      border: '#1e293b',
      primary: '#60a5fa',
    };
  }
  return {
    mode,
    bg: '#f8fafc',
    card: '#ffffff',
    text: '#0f172a',
    subtext: '#64748b',
    border: '#e2e8f0',
    primary: '#2563eb',
  };
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>('light');

  useEffect(() => {
    (async () => {
      const stored = await AsyncStorage.getItem(THEME_KEY);
      if (stored === 'dark' || stored === 'light') {
        setMode(stored);
      }
    })();
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: buildTheme(mode),
      toggleTheme: async () => {
        const next: ThemeMode = mode === 'light' ? 'dark' : 'light';
        setMode(next);
        await AsyncStorage.setItem(THEME_KEY, next);
      },
    }),
    [mode]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useAppTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useAppTheme must be used inside ThemeProvider');
  return ctx;
}

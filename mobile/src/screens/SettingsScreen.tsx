import React, { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useAppTheme } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import { api, getApiBaseUrl, setApiBaseUrl } from '../services/api';

export function SettingsScreen() {
  const { logout } = useAuth();
  const { theme, toggleTheme } = useAppTheme();
  const { showToast } = useToast();
  const [apiUrl, setApiUrl] = useState(getApiBaseUrl());

  async function saveApiUrl() {
    if (!apiUrl.trim().startsWith('http')) {
      showToast('API URL phai bat dau bang http:// hoac https://', 'error');
      return;
    }
    await setApiBaseUrl(apiUrl);
    showToast('Da luu API URL moi', 'success');
  }

  async function testConnection() {
    const res = await api.me();
    showToast(res.message || (res.success ? 'Ket noi OK' : 'Ket noi that bai'), res.success ? 'success' : 'error');
  }

  return (
    <View style={{ flex: 1, padding: 12, gap: 12, backgroundColor: theme.bg }}>
      <Text style={{ fontSize: 18, fontWeight: '700', color: theme.text }}>Cai dat mobile</Text>
      <Text style={{ color: theme.subtext }}>API Base URL</Text>
      <TextInput
        value={apiUrl}
        onChangeText={setApiUrl}
        autoCapitalize="none"
        autoCorrect={false}
        style={{ borderWidth: 1, borderRadius: 8, borderColor: theme.border, padding: 10, color: theme.text, backgroundColor: theme.card }}
        placeholder="http://172.20.10.4:5000"
        placeholderTextColor={theme.subtext}
      />
      <Pressable onPress={saveApiUrl} style={{ backgroundColor: theme.primary, borderRadius: 8, padding: 12 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>Luu API URL</Text>
      </Pressable>
      <Pressable onPress={testConnection} style={{ backgroundColor: '#0f766e', borderRadius: 8, padding: 12 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>Test ket noi backend</Text>
      </Pressable>
      <Pressable onPress={toggleTheme} style={{ backgroundColor: '#334155', borderRadius: 8, padding: 12 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>
          Chuyen sang {theme.mode === 'light' ? 'Dark' : 'Light'} mode
        </Text>
      </Pressable>
      <Pressable
        onPress={logout}
        style={{ marginTop: 10, backgroundColor: '#dc2626', borderRadius: 8, padding: 12 }}
      >
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>Dang xuat</Text>
      </Pressable>
    </View>
  );
}

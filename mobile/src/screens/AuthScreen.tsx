import React, { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { getApiBaseUrl, setApiBaseUrl } from '../services/api';

export function AuthScreen() {
  const { login, register } = useAuth();
  const { showToast } = useToast();
  const [isRegister, setIsRegister] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [apiUrl, setApiUrl] = useState(getApiBaseUrl());

  async function onSubmit() {
    const result = isRegister ? await register(name, email, password) : await login(email, password);
    if (!result.ok) {
      showToast(result.message || 'Dang nhap/dang ky that bai', 'error');
      return;
    }
    showToast(isRegister ? 'Dang ky thanh cong' : 'Dang nhap thanh cong', 'success');
  }

  async function onSaveApiUrl() {
    if (!apiUrl.trim().startsWith('http://') && !apiUrl.trim().startsWith('https://')) {
      showToast('API URL phai bat dau bang http:// hoac https://', 'error');
      return;
    }
    await setApiBaseUrl(apiUrl);
    showToast('Da luu API URL. Thu dang nhap/dang ky lai.', 'success');
  }

  return (
    <View style={{ flex: 1, padding: 16, justifyContent: 'center', gap: 10 }}>
      <Text style={{ fontSize: 22, fontWeight: '700' }}>EduConnect Mobile</Text>
      <TextInput
        placeholder="API URL (vd: http://172.20.10.4:5000)"
        value={apiUrl}
        onChangeText={setApiUrl}
        style={{ borderWidth: 1, padding: 10, borderRadius: 8 }}
        autoCapitalize="none"
        autoCorrect={false}
      />
      <Pressable onPress={onSaveApiUrl} style={{ backgroundColor: '#0f766e', padding: 10, borderRadius: 8 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>Luu API URL</Text>
      </Pressable>
      {isRegister && <TextInput placeholder="Ten" value={name} onChangeText={setName} style={{ borderWidth: 1, padding: 10, borderRadius: 8 }} />}
      <TextInput placeholder="Email" value={email} onChangeText={setEmail} style={{ borderWidth: 1, padding: 10, borderRadius: 8 }} autoCapitalize="none" />
      <TextInput placeholder="Mat khau" secureTextEntry value={password} onChangeText={setPassword} style={{ borderWidth: 1, padding: 10, borderRadius: 8 }} />
      <Pressable onPress={onSubmit} style={{ backgroundColor: '#2563eb', padding: 12, borderRadius: 8 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>{isRegister ? 'Dang ky' : 'Dang nhap'}</Text>
      </Pressable>
      <Pressable onPress={() => setIsRegister((v) => !v)}>
        <Text style={{ textAlign: 'center', color: '#334155' }}>
          {isRegister ? 'Da co tai khoan? Dang nhap' : 'Chua co tai khoan? Dang ky'}
        </Text>
      </Pressable>
    </View>
  );
}

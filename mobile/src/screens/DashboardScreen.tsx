import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useAppTheme } from '../context/ThemeContext';
import { api } from '../services/api';
import { AiProfile } from '../types';

function riskColor(level?: string) {
  if (level === 'high') return '#dc2626';
  if (level === 'medium') return '#d97706';
  return '#16a34a';
}

function clampPercent(n?: number) {
  const v = Number(n || 0);
  if (v < 0) return 0;
  if (v > 100) return 100;
  return v;
}

export function DashboardScreen() {
  const { user } = useAuth();
  const { theme } = useAppTheme();
  const [profile, setProfile] = useState<AiProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    const res = await api.aiProfile();
    if (res.success && res.data?.profile) setProfile(res.data.profile);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <ScrollView
      contentContainerStyle={{ padding: 14, gap: 12 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
      style={{ backgroundColor: theme.bg }}
    >
      <View style={{ backgroundColor: theme.card, padding: 14, borderRadius: 12, borderWidth: 1, borderColor: theme.border }}>
        <Text style={{ color: theme.text, fontSize: 18, fontWeight: '700' }}>Xin chao, {user?.name || 'ban'}</Text>
        <Text style={{ color: theme.subtext, marginTop: 4 }}>Tong quan hoc tap ca nhan hoa bang AI</Text>
      </View>

      {loading ? (
        <View style={{ paddingVertical: 28, alignItems: 'center' }}>
          <ActivityIndicator size="large" color="#2563eb" />
          <Text style={{ marginTop: 10, color: '#64748b' }}>Dang tai dashboard...</Text>
        </View>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 10 }}>
        <View style={{ flex: 1, backgroundColor: theme.card, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.border }}>
          <Text style={{ color: theme.subtext }}>Tien do TB</Text>
          <Text style={{ fontSize: 22, fontWeight: '700', color: theme.text }}>{profile?.avg_progress ?? 0}%</Text>
        </View>
        <View style={{ flex: 1, backgroundColor: theme.card, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.border }}>
          <Text style={{ color: theme.subtext }}>Risk score</Text>
          <Text style={{ fontSize: 22, fontWeight: '700', color: riskColor(profile?.risk_level) }}>{profile?.risk_score ?? 0}</Text>
        </View>
      </View>

      <View style={{ backgroundColor: theme.card, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.border }}>
        <Text style={{ fontWeight: '700', marginBottom: 10, color: theme.text }}>Mini chart</Text>
        <Text style={{ color: theme.subtext, marginBottom: 6 }}>Tien do hoc tap</Text>
        <View style={{ height: 10, borderRadius: 999, backgroundColor: theme.border, overflow: 'hidden', marginBottom: 12 }}>
          <View style={{ width: `${clampPercent(profile?.avg_progress)}%`, height: '100%', backgroundColor: '#22c55e' }} />
        </View>
        <Text style={{ color: theme.subtext, marginBottom: 6 }}>Risk score</Text>
        <View style={{ height: 10, borderRadius: 999, backgroundColor: theme.border, overflow: 'hidden' }}>
          <View style={{ width: `${clampPercent(profile?.risk_score)}%`, height: '100%', backgroundColor: riskColor(profile?.risk_level) }} />
        </View>
      </View>

      <View style={{ backgroundColor: theme.card, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.border }}>
        <Text style={{ fontWeight: '700', marginBottom: 6, color: theme.text }}>AI reminder</Text>
        <Text style={{ color: theme.text, marginBottom: 6 }}>{profile?.reminder?.title || 'Dang cap nhat'}</Text>
        <Text style={{ color: theme.subtext }}>{profile?.reminder?.message || 'Khong co du lieu reminder.'}</Text>
      </View>

      <View style={{ backgroundColor: theme.card, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: theme.border }}>
        <Text style={{ fontWeight: '700', marginBottom: 8, color: theme.text }}>Ke hoach tiep theo</Text>
        {(profile?.next_steps || []).slice(0, 3).map((step, idx) => (
          <Text key={idx} style={{ color: theme.subtext, marginBottom: 6 }}>
            {idx + 1}. {step}
          </Text>
        ))}
      </View>
    </ScrollView>
  );
}

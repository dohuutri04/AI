import React, { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from 'react-native';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { TeacherApplication, TeacherJob } from '../types';

function statusLabel(status: string) {
  if (status === 'accepted') return 'Da duyet';
  if (status === 'rejected') return 'Tu choi';
  if (status === 'shortlisted') return 'Shortlist';
  return 'Dang cho';
}

function statusColor(status: string) {
  if (status === 'accepted') return '#166534';
  if (status === 'rejected') return '#b91c1c';
  if (status === 'shortlisted') return '#1d4ed8';
  return '#92400e';
}

export function RecruitmentScreen() {
  const [jobs, setJobs] = useState<TeacherJob[]>([]);
  const [history, setHistory] = useState<TeacherApplication[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const { showToast } = useToast();
  const [bio, setBio] = useState('');
  const [exp, setExp] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');

  async function loadData() {
    const jobsRes = await api.teacherJobs();
    if (jobsRes.success && jobsRes.data?.jobs) setJobs(jobsRes.data.jobs);
    const historyRes = await api.myTeacherApplications();
    if (historyRes.success && historyRes.data?.applications) setHistory(historyRes.data.applications);
    setLoading(false);
  }

  useEffect(() => {
    loadData();
  }, []);

  async function submitApplication() {
    if (!selectedJobId) {
      showToast('Vui long chon job', 'error');
      return;
    }
    setSubmitting(true);
    const res = await api.applyTeacherJob(selectedJobId, {
      bio,
      experience_summary: exp,
      contact_email: email,
      contact_phone: phone,
    });
    showToast(res.message || (res.success ? 'Thanh cong' : 'That bai'), res.success ? 'success' : 'error');
    if (res.success) {
      setBio('');
      setExp('');
      setPhone('');
      await loadData();
    }
    setSubmitting(false);
  }

  return (
    <ScrollView
      contentContainerStyle={{ padding: 12, gap: 14 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={loadData} />}
    >
      <Text style={{ fontSize: 20, fontWeight: '700' }}>Tuyen giao vien</Text>
      <Text style={{ color: '#64748b' }}>Chon job, nop ho so va theo doi trang thai duyet.</Text>
      {loading ? (
        <View style={{ paddingVertical: 20, alignItems: 'center' }}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : (
      <FlatList
        data={jobs}
        keyExtractor={(i) => String(i.id)}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => setSelectedJobId(item.id)}
            style={({ pressed }) => ({
              borderWidth: 1,
              borderColor: selectedJobId === item.id ? '#2563eb' : '#cbd5e1',
              borderRadius: 8,
              padding: 10,
              marginBottom: 8,
              transform: [{ scale: pressed ? 0.99 : 1 }],
              opacity: pressed ? 0.94 : 1,
            })}
          >
            <Text style={{ fontWeight: '700' }}>{item.title}</Text>
            <Text style={{ color: '#475569' }}>{item.course_title}</Text>
          </Pressable>
        )}
      />
      )}

      <Text style={{ fontWeight: '700', marginTop: 4 }}>Nop ho so ung tuyen</Text>
      <TextInput value={bio} onChangeText={setBio} placeholder="Gioi thieu ban than" style={{ borderWidth: 1, borderRadius: 8, padding: 10 }} />
      <TextInput value={exp} onChangeText={setExp} placeholder="Kinh nghiem" style={{ borderWidth: 1, borderRadius: 8, padding: 10 }} />
      <TextInput value={email} onChangeText={setEmail} placeholder="Email lien he" style={{ borderWidth: 1, borderRadius: 8, padding: 10 }} autoCapitalize="none" />
      <TextInput value={phone} onChangeText={setPhone} placeholder="So dien thoai" style={{ borderWidth: 1, borderRadius: 8, padding: 10 }} />
      <Pressable onPress={submitApplication} style={{ backgroundColor: submitting ? '#059669' : '#16a34a', borderRadius: 8, padding: 12 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>
          {submitting ? 'Dang gui ho so...' : 'Ung tuyen + upload file'}
        </Text>
      </Pressable>

      <Text style={{ fontWeight: '700', marginTop: 8 }}>Lich su ung tuyen</Text>
      {history.map((item) => (
        <View key={item.id} style={{ borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 8, padding: 10, marginBottom: 8 }}>
          <Text style={{ fontWeight: '700' }}>{item.job_title}</Text>
          <Text style={{ color: '#64748b' }}>{item.course_title}</Text>
          <View style={{ alignSelf: 'flex-start', marginTop: 6, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: `${statusColor(item.status)}20` }}>
            <Text style={{ color: statusColor(item.status), fontWeight: '700' }}>{statusLabel(item.status)}</Text>
          </View>
          {!!item.review_note && <Text>Ghi chu: {item.review_note}</Text>}
        </View>
      ))}
    </ScrollView>
  );
}

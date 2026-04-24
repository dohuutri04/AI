import { useNavigation } from '@react-navigation/native';
import React, { useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, TextInput, View } from 'react-native';
import { useAppTheme } from '../context/ThemeContext';
import { api } from '../services/api';
import { Course } from '../types';

export function CoursesScreen() {
  const nav = useNavigation<any>();
  const { theme } = useAppTheme();
  const [courses, setCourses] = useState<Course[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');

  async function loadCourses() {
    setRefreshing(true);
    api.courses().then((res) => {
      if (res.success && res.data?.courses) setCourses(res.data.courses);
      setLoading(false);
      setRefreshing(false);
    });
  }

  React.useEffect(() => {
    loadCourses();
  }, []);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return courses;
    return courses.filter((c) => (c.title || '').toLowerCase().includes(query));
  }, [courses, q]);

  return (
    <View style={{ flex: 1, padding: 12, backgroundColor: theme.bg }}>
      <Text style={{ fontSize: 20, fontWeight: '700', marginBottom: 10, color: theme.text }}>Khoa hoc</Text>
      <TextInput
        value={q}
        onChangeText={setQ}
        placeholder="Tim theo ten khoa hoc..."
        style={{ borderWidth: 1, borderColor: theme.border, borderRadius: 10, padding: 10, marginBottom: 10, color: theme.text, backgroundColor: theme.card }}
        placeholderTextColor={theme.subtext}
      />
      {loading ? (
        <View style={{ paddingVertical: 24, alignItems: 'center' }}>
          <ActivityIndicator size="large" color="#2563eb" />
          <Text style={{ marginTop: 8, color: theme.subtext }}>Dang tai khoa hoc...</Text>
        </View>
      ) : (
      <FlatList
        data={filtered}
        keyExtractor={(i) => String(i.id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadCourses} />}
        ListEmptyComponent={<Text style={{ color: theme.subtext, textAlign: 'center', marginTop: 24 }}>Khong co khoa hoc phu hop</Text>}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => nav.navigate('CourseDetail', { courseId: item.id })}
            style={({ pressed }) => ({
              borderWidth: 1,
              borderColor: theme.border,
              borderRadius: 12,
              padding: 12,
              marginBottom: 10,
              backgroundColor: theme.card,
              transform: [{ scale: pressed ? 0.985 : 1 }],
              opacity: pressed ? 0.92 : 1,
            })}
          >
            <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text }}>{item.title}</Text>
            <Text style={{ color: theme.subtext, marginTop: 4 }}>{item.instructor_name || 'Unknown instructor'}</Text>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 }}>
              <Text style={{ color: theme.text, fontWeight: '700' }}>{Number(item.price || 0).toLocaleString()} VND</Text>
              <Text style={{ color: theme.primary }}>Xem chi tiet</Text>
            </View>
          </Pressable>
        )}
      />
      )}
    </View>
  );
}

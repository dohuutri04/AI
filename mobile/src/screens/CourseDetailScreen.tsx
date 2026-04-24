import { RouteProp, useRoute } from '@react-navigation/native';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { Course, Lesson } from '../types';

export function CourseDetailScreen() {
  const route = useRoute<RouteProp<{ params: { courseId: number } }, 'params'>>();
  const [course, setCourse] = useState<Course | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [enrolled, setEnrolled] = useState(false);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();

  useEffect(() => {
    api.courseDetail(route.params.courseId).then((res) => {
      if (res.success && res.data) {
        setCourse(res.data.course);
        setLessons(res.data.lessons);
      }
      setLoading(false);
    });
  }, [route.params.courseId]);

  async function onEnroll() {
    const res = await api.enroll(route.params.courseId);
    if (res.success) setEnrolled(true);
    showToast(res.message || (res.success ? 'Thanh cong' : 'That bai'), res.success ? 'success' : 'error');
  }

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#f8fafc' }}>
        <ActivityIndicator size="large" color="#2563eb" />
      </View>
    );
  }
  if (!course) return <View style={{ flex: 1 }} />;

  return (
    <ScrollView contentContainerStyle={{ padding: 12, gap: 10 }}>
      <View style={{ backgroundColor: '#0f172a', padding: 14, borderRadius: 12 }}>
        <Text style={{ fontSize: 20, fontWeight: '700', color: '#fff' }}>{course.title}</Text>
        <Text style={{ color: '#cbd5e1', marginTop: 6 }}>{course.description}</Text>
        <Text style={{ color: '#e2e8f0', marginTop: 8 }}>
          Gia: {Number(course.price || 0).toLocaleString()} VND | Level: {course.level || 'beginner'}
        </Text>
      </View>
      <Pressable onPress={onEnroll} style={{ backgroundColor: enrolled ? '#0f766e' : '#16a34a', padding: 12, borderRadius: 8 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>
          {enrolled ? 'Da dang ky khoa hoc' : 'Dang ky khoa hoc'}
        </Text>
      </Pressable>
      <Text style={{ marginTop: 8, fontWeight: '700' }}>Danh sach bai hoc</Text>
      {lessons.map((lesson) => (
        <View key={lesson.id} style={{ borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 10, padding: 12, backgroundColor: '#fff' }}>
          <Text style={{ fontWeight: '600' }}>{lesson.title}</Text>
          <Text style={{ color: '#64748b', marginTop: 4 }}>
            {lesson.duration_minutes || 0} phut {lesson.is_free ? '- Bai mien phi' : ''}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

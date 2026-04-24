import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { api } from '../services/api';
import { Course, Lesson } from '../types';

export function LearningScreen() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<number | null>(null);
  const [courseLessons, setCourseLessons] = useState<Lesson[]>([]);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [quizAnswer, setQuizAnswer] = useState('A');
  const [result, setResult] = useState<string>('');
  const [exerciseId, setExerciseId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.courses().then((res) => {
      if (res.success && res.data?.courses) {
        setCourses(res.data.courses);
        if (res.data.courses.length > 0) {
          setSelectedCourseId(res.data.courses[0].id);
        }
      }
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!selectedCourseId) return;
    api.courseDetail(selectedCourseId).then((res) => {
      if (res.success && res.data?.lessons) {
        setCourseLessons(res.data.lessons);
        if (res.data.lessons.length > 0) {
          const firstLesson = res.data.lessons[0];
          setLesson(firstLesson);
        }
      }
    });
  }, [selectedCourseId]);

  useEffect(() => {
    if (!lesson?.id) return;
    api.lessonDetail(lesson.id).then((res) => {
      if (res.success && res.data?.lesson) {
        setLesson(res.data.lesson);
        const firstExercise = (res.data.exercises || [])[0];
        setExerciseId(firstExercise ? Number(firstExercise.id) : null);
      }
    });
  }, [lesson?.id]);

  async function submitQuiz() {
    if (!lesson) return;
    if (!exerciseId) {
      Alert.alert('Thong bao', 'Bai hoc nay chua co quiz.');
      return;
    }
    const response = await api.submitQuiz(lesson.id, { [String(exerciseId)]: quizAnswer });
    if (!response.success) {
      Alert.alert('Loi', response.message || 'Nop quiz that bai');
      return;
    }
    setResult(`Diem: ${response.data?.score_pct || 0}% - Tien do: ${response.data?.course_progress_pct || 0}%`);
  }

  return (
    <ScrollView contentContainerStyle={{ padding: 12, gap: 10 }}>
      <Text style={{ fontSize: 18, fontWeight: '700' }}>Hoc bai va quiz</Text>
      {loading ? (
        <View style={{ paddingVertical: 20, alignItems: 'center' }}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : null}
      <Text style={{ fontWeight: '700' }}>Chon khoa hoc</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {courses.map((course) => (
            <Pressable
              key={course.id}
              onPress={() => setSelectedCourseId(course.id)}
              style={{
                borderWidth: 1,
                borderColor: selectedCourseId === course.id ? '#2563eb' : '#cbd5e1',
                borderRadius: 999,
                paddingVertical: 8,
                paddingHorizontal: 12,
              }}
            >
              <Text>{course.title}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
      <Text style={{ fontWeight: '700' }}>Chon bai hoc</Text>
      <View style={{ gap: 8 }}>
        {courseLessons.map((item) => (
          <Pressable
            key={item.id}
            onPress={() => setLesson(item)}
            style={({ pressed }) => ({
              borderWidth: 1,
              borderColor: lesson?.id === item.id ? '#2563eb' : '#e2e8f0',
              borderRadius: 8,
              padding: 10,
              transform: [{ scale: pressed ? 0.99 : 1 }],
              opacity: pressed ? 0.94 : 1,
            })}
          >
            <Text>{item.title}</Text>
          </Pressable>
        ))}
      </View>
      {lesson ? (
        <View style={{ borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 8, padding: 10 }}>
          <Text style={{ fontWeight: '700' }}>{lesson.title}</Text>
          <Text style={{ color: '#475569' }}>Video: {lesson.video_url || 'N/A'}</Text>
        </View>
      ) : null}
      <TextInput value={quizAnswer} onChangeText={setQuizAnswer} style={{ borderWidth: 1, borderRadius: 8, padding: 10 }} placeholder="Dap an quiz (A/B/C/D)" />
      <Text style={{ color: '#64748b' }}>
        {exerciseId ? `Dang nop cho cau hoi ID: ${exerciseId}` : 'Khong co cau hoi quiz trong bai nay'}
      </Text>
      <Pressable onPress={submitQuiz} style={{ backgroundColor: '#2563eb', padding: 12, borderRadius: 8 }}>
        <Text style={{ color: '#fff', textAlign: 'center', fontWeight: '700' }}>Nop quiz</Text>
      </Pressable>
      {result ? <Text>{result}</Text> : null}
    </ScrollView>
  );
}

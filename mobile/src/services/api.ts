import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AiProfile, ApiEnvelope, Course, Lesson, TeacherApplication, TeacherJob, User } from '../types';

const API_BASE_URL_KEY = 'api_base_url';
const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || 'http://127.0.0.1:5000';
let runtimeBaseUrl = DEFAULT_BASE_URL;

export async function initializeApiBaseUrl() {
  const stored = await AsyncStorage.getItem(API_BASE_URL_KEY);
  if (stored && stored.trim()) {
    runtimeBaseUrl = stored.trim();
  }
}

export function getApiBaseUrl() {
  return runtimeBaseUrl;
}

export async function setApiBaseUrl(nextUrl: string) {
  runtimeBaseUrl = nextUrl.trim();
  await AsyncStorage.setItem(API_BASE_URL_KEY, runtimeBaseUrl);
}

async function request<T>(path: string, options?: RequestInit): Promise<ApiEnvelope<T>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const resp = await fetch(`${runtimeBaseUrl}${path}`, {
      credentials: 'include',
      headers: {
        ...(options?.headers || {}),
      },
      ...options,
      signal: controller.signal,
    });
    return resp.json();
  } catch (error) {
    return {
      success: false,
      message: `Khong ket noi duoc server API (${runtimeBaseUrl}). Kiem tra API URL va backend Flask.`,
      data: undefined,
      error_code: 'NETWORK_ERROR',
    };
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  login(email: string, password: string) {
    const body = new URLSearchParams({ email, password }).toString();
    return request<{ user: User }>('/api/mobile/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  },
  register(name: string, email: string, password: string) {
    const body = new URLSearchParams({ name, email, password }).toString();
    return request<{ user: User }>('/api/mobile/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  },
  me() {
    return request<{ user: User }>('/api/mobile/auth/me');
  },
  logout() {
    return request<null>('/api/mobile/auth/logout', { method: 'POST' });
  },
  courses() {
    return request<{ courses: Course[] }>('/api/mobile/courses');
  },
  courseDetail(courseId: number) {
    return request<{ course: Course; lessons: Lesson[] }>(`/api/mobile/courses/${courseId}`);
  },
  enroll(courseId: number) {
    return request<{ first_lesson_id?: number }>(`/api/mobile/courses/${courseId}/enroll`, { method: 'POST' });
  },
  lessonDetail(lessonId: number) {
    return request<{ lesson: Lesson; materials: any[]; exercises: any[]; all_lessons: Lesson[] }>(
      `/api/mobile/lessons/${lessonId}`
    );
  },
  submitQuiz(lessonId: number, answers: Record<string, string>) {
    const body = new URLSearchParams({
      lesson_id: String(lessonId),
      answers_json: JSON.stringify(answers),
    }).toString();
    return request<any>('/submit-lesson-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  },
  teacherJobs() {
    return request<{ jobs: TeacherJob[] }>('/api/mobile/teacher-jobs');
  },
  myTeacherApplications() {
    return request<{ applications: TeacherApplication[] }>('/api/mobile/my-teacher-applications');
  },
  aiProfile() {
    return request<{ profile: AiProfile }>('/api/mobile/ai-profile');
  },
  async applyTeacherJob(jobId: number, payload: { bio: string; experience_summary: string; contact_email: string; contact_phone: string }) {
    const form = new FormData();
    form.append('bio', payload.bio);
    form.append('experience_summary', payload.experience_summary);
    form.append('contact_email', payload.contact_email);
    form.append('contact_phone', payload.contact_phone);

    const cv = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'application/msword'] });
    if (!cv.canceled && cv.assets.length > 0) {
      const file = cv.assets[0];
      form.append('cv_file', { uri: file.uri, name: file.name, type: file.mimeType || 'application/pdf' } as any);
    }
    const cert = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'image/*'] });
    if (!cert.canceled && cert.assets.length > 0) {
      const file = cert.assets[0];
      form.append('certificate_file', { uri: file.uri, name: file.name, type: file.mimeType || 'application/pdf' } as any);
    }
    const image = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.8 });
    if (!image.canceled && image.assets.length > 0) {
      const file = image.assets[0];
      form.append('avatar_file', { uri: file.uri, name: file.fileName || 'avatar.jpg', type: file.mimeType || 'image/jpeg' } as any);
    }

    return request<null>(`/teacher-jobs/${jobId}/apply`, { method: 'POST', body: form as any });
  },
};

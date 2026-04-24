export type ApiEnvelope<T> = {
  success: boolean;
  message?: string;
  data?: T;
  error_code?: string;
};

export type User = {
  id: number;
  name: string;
  email: string;
};

export type Course = {
  id: number;
  title: string;
  description?: string;
  price?: number;
  instructor_name?: string;
  level?: string;
  total_lessons?: number;
};

export type Lesson = {
  id: number;
  title: string;
  course_id: number;
  duration_minutes?: number;
  video_url?: string;
  is_free?: number;
};

export type TeacherJob = {
  id: number;
  course_id: number;
  course_title?: string;
  title: string;
  description: string;
  requirements?: string;
  status?: string;
  owner_name?: string;
};

export type TeacherApplication = {
  id: number;
  job_title: string;
  course_title: string;
  owner_name: string;
  status: 'pending' | 'shortlisted' | 'accepted' | 'rejected';
  review_note?: string;
  created_at?: string;
  reviewed_at?: string;
};

export type AiProfile = {
  segment: string;
  avg_progress: number;
  risk_level: 'low' | 'medium' | 'high';
  risk_score: number;
  next_steps: string[];
  reminder?: { title: string; message: string };
  next_lessons?: Array<{ lesson_id: number; lesson_title: string; course_title: string; progress: number }>;
};

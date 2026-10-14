const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:3000/api';

let _token: string | null = null;

export function setToken(token: string) {
  _token = token;
  if (typeof window !== 'undefined') {
    localStorage.setItem('biq_token', token);
  }
}

export function getToken(): string | null {
  if (_token) return _token;
  if (typeof window !== 'undefined') {
    return localStorage.getItem('biq_token');
  }
  return null;
}

export function clearToken() {
  _token = null;
  if (typeof window !== 'undefined') {
    localStorage.removeItem('biq_token');
  }
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  role: string;
  is_active: boolean;
  password_change_required?: boolean;
}

/**
 * Authenticate with explicit credentials. There is intentionally NO automatic
 * login with default credentials — callers (the login screen) must supply the
 * username and password entered by the user.
 */
export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let detail = 'Invalid username or password';
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {
      // Non-JSON error body — keep the default message.
    }
    const err: any = new Error(detail);
    err.status = res.status;
    throw err;
  }
  const data: LoginResult = await res.json();
  setToken(data.access_token);
  return data;
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  if (!token) {
    const err: any = new Error('Not authenticated');
    err.status = 401;
    throw err;
  }
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
  if (res.status === 401) {
    // Token expired or revoked — drop it so the app falls back to the login screen.
    clearToken();
    const err: any = new Error('Session expired. Please sign in again.');
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${path} failed: ${res.status} ${text}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

/* ── Dashboard ─────────────────────────────────────────────── */

export function getDashboardOverview() {
  return apiFetch('/dashboard/overview');
}

/* ── Manual full-system run (header button) ─────────────────── */

export interface SystemRunStatus {
  phase: 'idle' | 'scraping' | 'analyzing' | 'done' | 'failed';
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export function triggerSystemRun(): Promise<{ status: string; phase: string }> {
  return apiFetch('/system/run', { method: 'POST', body: '{}' });
}

export function getSystemRunStatus(): Promise<SystemRunStatus> {
  return apiFetch('/system/run/status');
}

export function getDashboardSources() {
  return apiFetch('/dashboard/sources');
}

export function getTopicsTrend(days?: number) {
  const qs = days ? `?days=${days}` : '';
  return apiFetch(`/dashboard/topics-trend${qs}`);
}

export function getTopicCards() {
  return apiFetch('/dashboard/topic-cards');
}

/* ── Comments ──────────────────────────────────────────────── */

export interface CommentItem {
  comment_id: string;
  text_content: string;
  source: string;
  scraped_at: string;
  sentiment: string;
  topic: string;
  cluster_id: number;
  like_count: number;
  created_at: string;
  is_reply: boolean;
  fallback_used: boolean;
  repliable: boolean;
  reply_blocked_reason: string | null;
  human_verified: boolean;
  verified_by: string | null;
}

export interface CommentsResponse {
  total_comments: number;
  sentiment: { positive: number; neutral: number; negative: number };
  sources: { source: string; count: number }[];
  comments: CommentItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export function getComments(params?: {
  limit?: number;
  cursor?: string;
  source?: string;
  sentiment?: string;
  topic?: string;
}): Promise<CommentsResponse> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.cursor) qs.set('cursor', params.cursor);
  if (params?.source) qs.set('source', params.source);
  if (params?.sentiment) qs.set('sentiment', params.sentiment);
  if (params?.topic) qs.set('topic', params.topic);
  return apiFetch(`/comments?${qs.toString()}`);
}

export function getCommentsCount(params?: {
  source?: string;
  sentiment?: string;
  topic?: string;
}): Promise<{
  total: number;
  sentiment: { positive: number; neutral: number; negative: number };
  sources: { source: string; count: number }[];
}> {
  const qs = new URLSearchParams();
  if (params?.source) qs.set('source', params.source);
  if (params?.sentiment) qs.set('sentiment', params.sentiment);
  if (params?.topic) qs.set('topic', params.topic);
  return apiFetch(`/comments/count?${qs.toString()}`);
}

/* ── Topics ────────────────────────────────────────────────── */

export function getTopicsList(): Promise<string[]> {
  return apiFetch('/topics/list').then((data: any) => data?.topics || []);
}

export function getTopics(): Promise<any[]> {
  return apiFetch('/topics').then((data: any) => data?.topics || []);
}

export function getTopicComments(topic: string, params?: { limit?: number; cursor?: string }) {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.cursor) qs.set('cursor', params.cursor);
  return apiFetch(`/topics/${encodeURIComponent(topic)}/comments?${qs.toString()}`);
}

/* ── Sources ───────────────────────────────────────────────── */

export function getSources(): Promise<any> {
  return apiFetch('/sources');
}

export function createSource(body: any): Promise<any> {
  return apiFetch('/sources', { method: 'POST', body: JSON.stringify(body) });
}

export function updateSource(id: number, body: any): Promise<any> {
  return apiFetch(`/sources/${id}`, { method: 'PUT', body: JSON.stringify(body) });
}

export function deleteSource(id: number): Promise<any> {
  return apiFetch(`/sources/${id}`, { method: 'DELETE' });
}

export function getSourceHealth(id: number): Promise<any> {
  return apiFetch(`/sources/${id}/health`);
}

export function refreshSource(id: number): Promise<any> {
  return apiFetch(`/sources/${id}/refresh`, { method: 'POST', body: '{}' });
}

export function getScraperSettings(): Promise<any> {
  return apiFetch('/scraper/settings');
}

export function updateScraperSettings(body: any): Promise<any> {
  return apiFetch('/scraper/settings', { method: 'PUT', body: JSON.stringify(body) });
}

/* ── Pipeline Settings ──────────────────────────────────────── */

export function getPipelineSettings(): Promise<any> {
  return apiFetch('/settings/pipeline');
}

export function updatePipelineSettings(body: any): Promise<any> {
  return apiFetch('/settings/pipeline', { method: 'PUT', body: JSON.stringify(body) });
}

export function validateCron(cron: string): Promise<any> {
  return apiFetch('/settings/pipeline/validate-cron', {
    method: 'POST',
    body: JSON.stringify({ cron }),
  });
}

/* ── Word Cloud ────────────────────────────────────────────── */

export function getWordCloud(source?: string): Promise<any> {
  const qs = new URLSearchParams();
  if (source) qs.set('source', source);
  return apiFetch(`/dashboard/word-cloud?${qs.toString()}`);
}

export function getWordCloudSettings(): Promise<any> {
  return apiFetch('/word-cloud/settings');
}

export function updateWordCloudSettings(body: any): Promise<any> {
  return apiFetch('/word-cloud/settings', { method: 'PUT', body: JSON.stringify(body) });
}

export function addWordCloudWord(word: string): Promise<any> {
  return apiFetch('/word-cloud/words', { method: 'POST', body: JSON.stringify({ word }) });
}

export function removeWordCloudWord(word: string): Promise<any> {
  return apiFetch(`/word-cloud/words/${encodeURIComponent(word)}`, { method: 'DELETE' });
}

export function hideWordCloudWord(word: string): Promise<any> {
  return apiFetch(`/word-cloud/words/${encodeURIComponent(word)}/hide`, { method: 'PUT' });
}

/* ── Group Reply ───────────────────────────────────────────── */

export interface ReplyAck {
  campaign_id: number;
  accepted: number;
  skipped: { not_repliable: number; already_queued: number };
  eta: string;
  message: string;
}

export function submitReplies(body: {
  reply_text: string;
  comment_ids?: string[];
  filter?: { topic?: string; sentiment?: string };
  select_all_matching?: boolean;
}): Promise<ReplyAck> {
  return apiFetch('/replies', { method: 'POST', body: JSON.stringify(body) });
}

export function getReplies(limit?: number): Promise<any> {
  const qs = limit ? `?limit=${limit}` : '';
  return apiFetch(`/replies${qs}`);
}

export function getReply(id: number): Promise<any> {
  return apiFetch(`/replies/${id}`);
}

/* ── Label Feedback ────────────────────────────────────────── */

export interface FeedbackAck {
  comment_id: string;
  effective_topic: string;
  effective_sentiment: string;
  locked: boolean;
}

export function submitFeedback(body: {
  comment_id: string;
  new_topic?: string;
  new_sentiment?: string;
}): Promise<FeedbackAck> {
  return apiFetch('/feedback', { method: 'POST', body: JSON.stringify(body) });
}

export function submitFeedbackBulk(body: {
  comment_ids: string[];
  new_topic?: string;
  new_sentiment?: string;
}): Promise<{ batch_id: string; applied: string[]; skipped: { comment_id: string; reason: string }[] }> {
  return apiFetch('/feedback/bulk', { method: 'POST', body: JSON.stringify(body) });
}

/* ── Auth & User ───────────────────────────────────────────── */

export function getMe(): Promise<any> {
  return apiFetch('/me');
}

export function logout(): Promise<any> {
  return apiFetch('/auth/logout', { method: 'POST', body: '{}' });
}

export function changePassword(oldPassword: string, newPassword: string): Promise<any> {
  return apiFetch('/me/password', {
    method: 'PUT',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

/* ── Users (admin) ─────────────────────────────────────────── */

export function getUsers(): Promise<any[]> {
  return apiFetch('/users');
}

export function createUser(body: any): Promise<any> {
  return apiFetch('/users', { method: 'POST', body: JSON.stringify(body) });
}

export function updateUser(id: number, body: any): Promise<any> {
  return apiFetch(`/users/${id}`, { method: 'PUT', body: JSON.stringify(body) });
}

export function deleteUser(id: number): Promise<any> {
  return apiFetch(`/users/${id}`, { method: 'DELETE' });
}

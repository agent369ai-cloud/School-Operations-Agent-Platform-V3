// Typed fetch client for the School Operations API.
// Token is held in localStorage (this is a real Next app, not a sandboxed
// artifact) and attached as a bearer header. All calls go through `request`
// so error handling and auth are consistent.

export type Role = "admin" | "teacher" | "student" | "guardian";

export interface Session {
  access_token: string;
  role: Role;
  school_id: string;
  user_id: string;
  full_name: string;
}

const TOKEN_KEY = "school_ops_session";

export function saveSession(s: Session) {
  if (typeof window !== "undefined") localStorage.setItem(TOKEN_KEY, JSON.stringify(s));
}
export function loadSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(TOKEN_KEY);
  return raw ? (JSON.parse(raw) as Session) : null;
}
export function clearSession() {
  if (typeof window !== "undefined") localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; auth?: boolean; form?: FormData } = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.auth !== false) {
    const s = loadSession();
    if (s) headers["Authorization"] = `Bearer ${s.access_token}`;
  }
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`/api${path}`, { method: opts.method || "GET", headers, body });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail)) detail = j.detail.map((d: {msg?: string}) => d.msg ?? JSON.stringify(d)).join(", ");
      else if (j.detail) detail = JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    if (res.status === 401 && opts.auth !== false) {
      clearSession();
      if (typeof window !== "undefined") window.location.href = "/login";
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Endpoint helpers --------------------------------------------------------
export const api = {
  registerSchool: (b: {
    school_name: string; admin_name: string; admin_email: string; admin_password: string;
  }) => request<Session>("/auth/register", { method: "POST", body: b, auth: false }),

  login: (b: { email: string; password: string }) =>
    request<Session>("/auth/login", { method: "POST", body: b, auth: false }),

  acceptInvite: (b: { token: string; full_name: string; email?: string; password?: string }) =>
    request<Session>("/auth/invites/accept", { method: "POST", body: b, auth: false }),

  createInvite: (b: {
    role: Role; email?: string; class_id?: string; target_student_id?: string;
  }) => request<{ invite_id: string; token: string; role: Role; expires_at: string }>(
    "/auth/invites", { method: "POST", body: b }),

  listClasses: () => request<{ id: string; name: string; grade_level: string | null }[]>(
    "/admin/classes"),
  createClass: (b: { name: string; grade_level?: string }) =>
    request<{ id: string; name: string; grade_level: string | null }>(
      "/admin/classes", { method: "POST", body: b }),
  deleteClass: (id: string) =>
    request<void>(`/admin/classes/${id}`, { method: "DELETE" }),
  assignTeacher: (b: { teacher_id: string; class_id: string }) =>
    request<{ status: string }>("/admin/teacher-assignments", { method: "POST", body: b }),
  listUsers: () => request<{ id: string; full_name: string; role: Role; email: string | null }[]>(
    "/admin/users"),
  getPolicy: () => request<Record<string, unknown>>("/admin/policy"),
  setPolicy: (p: Record<string, unknown>) =>
    request<{ status: string }>("/admin/policy", { method: "PUT", body: p }),

  uploadDocument: (docType: string, file: File) => {
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("file", file);
    return request<DocumentDTO>("/documents/upload", { method: "POST", form });
  },
  listDocuments: () => request<DocumentDTO[]>("/documents"),
  approveDoc: (id: string, overrides?: Record<string, unknown>) =>
    request<DocumentDTO>(`/documents/${id}/approve`, { method: "POST", body: { overrides } }),
  rejectDoc: (id: string) =>
    request<DocumentDTO>(`/documents/${id}/reject`, { method: "POST", body: {} }),

  listAssignments: () => request<AssignmentDTO[]>("/assignments"),
  createAssignment: (b: {
    title: string; class_id?: string; subject?: string; instructions?: string;
    due_at?: string;
  }) => request<AssignmentDTO>("/assignments", { method: "POST", body: b }),
  transitionAssignment: (id: string, to: string) =>
    request<AssignmentDTO>(`/assignments/${id}/transition`, { method: "POST", body: { to } }),

  uploadSubmissionFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ document_id: string; filename: string }>(
      "/documents/student-upload", { method: "POST", form });
  },

  submit: (b: { assignment_id: string; body_text?: string; document_id?: string }) =>
    request<{ id: string; attempt: number; state: string }>(
      "/submissions", { method: "POST", body: b }),
  reportProgress: (b: { assignment_id: string; blocked: boolean; note?: string }) =>
    request<{ progress_state: string }>("/progress", { method: "POST", body: b }),
  giveFeedback: (b: { submission_id: string; body: string; decision?: string }) =>
    request<{ id: string; submission_state: string }>(
      "/feedback", { method: "POST", body: b }),
  runReminders: () => request<Record<string, unknown>>("/reminders/run", { method: "POST" }),

  teacherDashboard: () => request<TeacherDashboard>("/dashboard/teacher"),
  studentDashboard: () => request<StudentDashboard>("/dashboard/student"),
  adminDashboard: () => request<{ counts: Record<string, number> }>("/dashboard/admin"),

  audit: (correlationId?: string) =>
    request<AuditEvent[]>(`/audit${correlationId ? `?correlation_id=${correlationId}` : ""}`),

  teacherUnblock: (b: { assignment_id: string; student_id: string; note: string }) =>
    request<{ status: string; teacher_note: string }>(
      "/teacher/unblock", { method: "POST", body: b }),

  generateAiReview: (submissionId: string) =>
    request<TeacherDashboard["submissions_to_review"][0]["ai_review"]>(
      `/submissions/${submissionId}/ai-review`, { method: "POST" }),

  documentFileUrl: (documentId: string): string => {
    const s = loadSession();
    const token = s?.access_token ?? "";
    return `/api/documents/${documentId}/file?token=${encodeURIComponent(token)}`;
  },

  listMyStudents: () =>
    request<{ student_id: string; student_name: string; opted_in: boolean }[]>(
      "/guardian/students"),
  toggleOptIn: (studentId: string) =>
    request<{ student_id: string; opted_in: boolean }>(
      `/guardian/students/${studentId}/opt-in`, { method: "POST" }),
};

// --- DTO types ---------------------------------------------------------------
export interface DocumentDTO {
  id: string;
  doc_type: string;
  filename: string;
  review_state: string;
  confidence: number | null;
  ambiguities: string[] | null;
  clarifying_questions: string[] | null;
  parsed: Record<string, unknown> | null;
}
export interface AssignmentDTO {
  id: string; title: string; subject: string | null; instructions: string | null;
  due_at: string | null; state: string; class_id: string | null;
}
export interface TeacherDashboard {
  assignments: { id: string; title: string; state: string; due_at: string | null }[];
  blocked_students: {
    assignment_id: string; assignment_title: string | null;
    student_id: string; student_name: string;
    note: string | null; teacher_note: string | null;
  }[];
  submissions_to_review: {
    id: string; assignment_id: string; assignment_title: string | null;
    student_id: string; student_name: string; attempt: number; state: string;
    submitted_at: string | null; body_text: string | null;
    document_id: string | null; document_filename: string | null;
    ai_review: {
      summary: string; strengths: string[]; gaps: string[];
      suggested_decision: "complete" | "revision";
      suggested_feedback: string; confidence: number;
    } | null;
    prior_feedback: { body: string; decision: string | null; created_at: string | null }[];
  }[];
  documents_awaiting_review: {
    id: string; filename: string; doc_type: string; review_state: string;
    clarifying_questions: string[]; parsed: Record<string, unknown> | null;
  }[];
}
export interface StudentDashboard {
  assignments: {
    assignment_id: string; title: string; subject: string | null;
    instructions: string | null; due_at: string | null;
    progress_state: string; submission_state: string | null; attempts: number;
  }[];
}
export interface AuditEvent {
  id: string; created_at: string; event_type: string; summary: string;
  actor_label: string | null; correlation_id: string | null;
  resource_type: string | null; resource_id: string | null;
  detail: Record<string, unknown> | null;
}

// --- SSE subscription --------------------------------------------------------
export function subscribeEvents(onEvent: (e: { type: string; payload: unknown; at: string }) => void): () => void {
  const s = loadSession();
  if (!s) return () => {};
  // EventSource can't set headers, so we pass the token as a query param to a
  // same-origin proxy route. The browser keeps the connection open.
  const base = process.env.NEXT_PUBLIC_API_BASE || "";
  const url = `${base}/api/events/stream`;
  const es = new EventSource(url, { withCredentials: true });
  const handler = (ev: MessageEvent) => {
    try {
      onEvent(JSON.parse(ev.data));
    } catch {
      /* ignore keepalives */
    }
  };
  // Listen to the named events the backend emits.
  ["assignment.created", "assignment.state_changed", "submission.received",
   "progress.reported", "feedback.given"].forEach((t) =>
    es.addEventListener(t, handler as EventListener));
  es.onerror = () => { /* browser auto-reconnects */ };
  return () => es.close();
}

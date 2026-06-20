"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity, LogOut, LayoutGrid, GraduationCap, Users,
} from "lucide-react";
import {
  AuditEvent, Session, api, clearSession, loadSession, subscribeEvents,
} from "@/lib/api";

// State badge: color carries meaning, value renders in mono (the "ledger" idea).
const STATE_COLORS: Record<string, string> = {
  draft: "text-muted", published: "text-accent", active: "text-accent-dark",
  archived: "text-muted", cancelled: "text-muted",
  submitted: "text-accent", under_review: "text-accent-dark",
  revision_required: "text-blocked", completed: "text-ok",
  not_started: "text-muted", in_progress: "text-accent", blocked: "text-blocked",
  needs_clarification: "text-blocked", parsed: "text-accent", approved: "text-ok",
  rejected: "text-muted", failed: "text-blocked", pending_parse: "text-muted",
};

export function Badge({ value }: { value: string }) {
  const cls = STATE_COLORS[value] || "text-muted";
  return <span className={`badge ${cls}`}>{value.replace(/_/g, " ")}</span>;
}

export function Card({
  title, children, action,
}: { title?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="bg-surface border border-line rounded-lg shadow-card">
      {title && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-line">
          <h2 className="font-display text-lg text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Button({
  children, onClick, variant = "primary", type = "button", disabled,
}: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "primary" | "ghost" | "danger"; type?: "button" | "submit";
  disabled?: boolean;
}) {
  const styles = {
    primary: "bg-accent text-paper hover:bg-accent-dark",
    ghost: "bg-transparent text-ink border border-line hover:bg-paper",
    danger: "bg-blocked text-paper hover:opacity-90",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${styles} disabled:opacity-50`}>
      {children}
    </button>
  );
}

export function Field({
  label, ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block mb-3">
      <span className="block text-sm text-muted mb-1">{label}</span>
      <input {...props}
        className="w-full px-3 py-2 rounded-md border border-line bg-surface text-ink
                   focus:border-accent" />
    </label>
  );
}

const ROLE_HOME: Record<string, string> = {
  admin: "/admin", teacher: "/teacher", student: "/student", guardian: "/guardian",
};

const NAV: Record<string, { href: string; label: string; icon: React.ReactNode }[]> = {
  admin: [
    { href: "/admin", label: "Overview", icon: <LayoutGrid size={16} /> },
  ],
  teacher: [
    { href: "/teacher", label: "Operations", icon: <Activity size={16} /> },
  ],
  student: [
    { href: "/student", label: "My work", icon: <GraduationCap size={16} /> },
  ],
  guardian: [
    { href: "/guardian", label: "My children", icon: <Users size={16} /> },
  ],
};

// The console shell: left rail + main + optional live audit ribbon (admin only).
export function Shell({
  children, requiredRole,
}: { children: React.ReactNode; requiredRole?: string }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);

  useEffect(() => {
    const s = loadSession();
    if (!s) { router.replace("/login"); return; }
    // Redirect if this page requires a specific role and user has a different one.
    if (requiredRole && s.role !== requiredRole) {
      router.replace(ROLE_HOME[s.role] || "/login");
      return;
    }
    setSession(s);
    // Live activity ribbon is admin-only — skip audit fetch and SSE for other roles.
    if (s.role !== "admin") return;
    api.audit().then((a) => setEvents(a.slice(0, 30))).catch(() => {});
    const unsub = subscribeEvents((e) => {
      setEvents((prev) => [
        {
          id: Math.random().toString(36),
          created_at: e.at,
          event_type: e.type,
          summary: liveSummary(e.type, e.payload),
          actor_label: "live", correlation_id: null,
          resource_type: null, resource_id: null, detail: null,
        },
        ...prev,
      ].slice(0, 40));
    });
    return unsub;
  }, [router, requiredRole]);

  if (!session) return null;
  const nav = NAV[session.role] || [];
  const isAdmin = session.role === "admin";

  return (
    <div className={`min-h-screen grid ${isAdmin
      ? "grid-cols-[200px_1fr_320px] max-[1100px]:grid-cols-[180px_1fr]"
      : "grid-cols-[200px_1fr]"}`}>
      {/* Left rail */}
      <aside className="border-r border-line bg-surface flex flex-col">
        <div className="px-4 py-5 border-b border-line">
          <div className="font-display text-xl text-ink leading-none">Lincoln</div>
          <div className="machine text-muted mt-1">ops console</div>
        </div>
        <nav className="flex-1 p-2">
          {nav.map((n) => (
            <a key={n.href} href={n.href}
              className="flex items-center gap-2 px-3 py-2 rounded-md text-sm text-ink
                         hover:bg-paper">
              {n.icon} {n.label}
            </a>
          ))}
        </nav>
        <div className="p-3 border-t border-line">
          <div className="text-sm text-ink">{session.full_name}</div>
          <div className="machine text-muted mb-2">{session.role}</div>
          <button onClick={() => { clearSession(); router.replace("/login"); }}
            className="flex items-center gap-1.5 text-sm text-muted hover:text-blocked">
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="p-6 overflow-y-auto">{children}</main>

      {/* Live audit ribbon — admin only */}
      {isAdmin && (
        <aside className="border-l border-line bg-ink text-paper p-3 overflow-y-auto
                          max-[1100px]:hidden">
          <div className="flex items-center gap-1.5 mb-3 text-paper/80">
            <Activity size={14} /> <span className="machine">live activity</span>
          </div>
          <ul className="space-y-2">
            {events.map((e) => (
              <li key={e.id} className="animate-slidein border-b border-paper/10 pb-2">
                <div className="machine text-paper/60 text-[0.7rem]">
                  {new Date(e.created_at).toLocaleTimeString()} · {e.event_type}
                </div>
                <div className="text-sm text-paper/90">{e.summary}</div>
              </li>
            ))}
            {events.length === 0 && (
              <li className="machine text-paper/40">waiting for events…</li>
            )}
          </ul>
        </aside>
      )}
    </div>
  );
}

function liveSummary(type: string, payload: unknown): string {
  const p = (payload || {}) as Record<string, unknown>;
  switch (type) {
    case "assignment.created": return `Assignment created: ${p.title}`;
    case "assignment.state_changed": return `Assignment → ${p.state}`;
    case "submission.received": return `Submission received (attempt ${p.attempt})`;
    case "progress.reported": return p.blocked ? "Student reported BLOCKED" : "Progress reported";
    case "feedback.given": return `Feedback → ${p.submission_state}`;
    default: return type;
  }
}

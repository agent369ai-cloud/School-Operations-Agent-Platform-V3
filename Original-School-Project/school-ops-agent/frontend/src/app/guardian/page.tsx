"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, Shield } from "lucide-react";
import { Badge, Button, Card, Shell } from "@/components/ui";
import { AssignmentDTO, api, subscribeEvents } from "@/lib/api";

type LinkedStudent = { student_id: string; student_name: string; opted_in: boolean };

export default function GuardianPage() {
  const [assignments, setAssignments] = useState<AssignmentDTO[]>([]);
  const [linkedStudents, setLinkedStudents] = useState<LinkedStudent[]>([]);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const [list, studs] = await Promise.all([
      api.listAssignments(),
      api.listMyStudents(),
    ]);
    setAssignments(list);
    setLinkedStudents(studs);
    setLoading(false);
  }

  async function toggleOptIn(studentId: string) {
    setTogglingId(studentId);
    try {
      const updated = await api.toggleOptIn(studentId);
      setLinkedStudents((prev) =>
        prev.map((s) => s.student_id === studentId ? { ...s, opted_in: updated.opted_in } : s)
      );
    } finally {
      setTogglingId(null);
    }
  }

  useEffect(() => {
    refresh().catch(() => setLoading(false));
    const unsub = subscribeEvents(() => { refresh().catch(() => {}); });
    return unsub;
  }, []);

  const active = assignments.filter((a) => a.state === "active");
  const other = assignments.filter((a) => a.state !== "active");

  if (loading) return <Shell requiredRole="guardian"><div className="machine text-muted">loading…</div></Shell>;

  return (
    <Shell requiredRole="guardian">
      <h1 className="font-display text-3xl text-ink mb-1">My children&apos;s work</h1>
      <p className="text-muted mb-6">
        Assignments your children are enrolled in, updated live.
      </p>

      {/* Linked students + opt-in */}
      {linkedStudents.length > 0 && (
        <Card title="My children">
          <ul className="space-y-2 mb-1">
            {linkedStudents.map((s) => (
              <li key={s.student_id}
                className="flex items-center justify-between">
                <span className="text-sm text-ink font-medium">{s.student_name}</span>
                <Button
                  variant={s.opted_in ? "ghost" : "primary"}
                  onClick={() => toggleOptIn(s.student_id)}
                  disabled={togglingId === s.student_id}>
                  {s.opted_in
                    ? <><BellOff size={13} /> Notifications on</>
                    : <><Bell size={13} /> Enable notifications</>}
                </Button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted mt-2">
            Enable notifications to receive updates about your child&apos;s progress.
          </p>
        </Card>
      )}

      {/* Privacy notice */}
      <div className="flex items-start gap-2 bg-surface border border-line rounded-lg
                      px-4 py-3 my-4 text-sm text-muted">
        <Shield size={15} className="mt-0.5 shrink-0" />
        <span>
          You can see assignment titles, subjects, and due dates.
          Submission text and feedback are not shown here.
        </span>
      </div>

      {assignments.length === 0 ? (
        <Card>
          <p className="text-muted text-sm">
            No assignments yet. They will appear here once your child&apos;s
            teacher publishes work.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {active.length > 0 && (
            <Card title={`Active (${active.length})`}>
              <ul className="space-y-3">
                {active.map((a) => (
                  <AssignmentRow key={a.id} a={a} />
                ))}
              </ul>
            </Card>
          )}

          {other.length > 0 && (
            <Card title="Other">
              <ul className="space-y-3">
                {other.map((a) => (
                  <AssignmentRow key={a.id} a={a} />
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </Shell>
  );
}

function AssignmentRow({ a }: { a: AssignmentDTO }) {
  return (
    <li className="flex items-start justify-between border-b border-line last:border-0 pb-3 last:pb-0">
      <div>
        <div className="font-medium text-ink">{a.title}</div>
        {a.subject && (
          <div className="text-sm text-muted">{a.subject}</div>
        )}
        <div className="machine text-xs text-muted mt-0.5">
          {a.due_at
            ? `due ${new Date(a.due_at).toLocaleDateString(undefined, {
                weekday: "short", month: "short", day: "numeric",
              })}`
            : "no due date"}
        </div>
      </div>
      <Badge value={a.state} />
    </li>
  );
}

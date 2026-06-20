"use client";

import { useEffect, useState } from "react";
import { Shield } from "lucide-react";
import { Badge, Card, Shell } from "@/components/ui";
import { AssignmentDTO, api, subscribeEvents } from "@/lib/api";

export default function GuardianPage() {
  const [assignments, setAssignments] = useState<AssignmentDTO[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const list = await api.listAssignments();
    setAssignments(list);
    setLoading(false);
  }

  useEffect(() => {
    refresh().catch(() => setLoading(false));
    // Refresh when school activity happens (e.g. teacher activates an assignment).
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

      {/* Privacy notice */}
      <div className="flex items-start gap-2 bg-surface border border-line rounded-lg
                      px-4 py-3 mb-6 text-sm text-muted">
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

"use client";

import { useEffect, useState } from "react";
import { Hand, Send } from "lucide-react";
import { Badge, Button, Card, Shell } from "@/components/ui";
import { StudentDashboard, api } from "@/lib/api";

export default function StudentPage() {
  const [dash, setDash] = useState<StudentDashboard | null>(null);
  const [submitFor, setSubmitFor] = useState<string | null>(null);
  const [text, setText] = useState("");

  async function refresh() { setDash(await api.studentDashboard()); }
  useEffect(() => { refresh().catch(() => {}); }, []);

  async function report(assignmentId: string, blocked: boolean) {
    await api.reportProgress({ assignment_id: assignmentId, blocked });
    refresh();
  }
  async function submit(assignmentId: string) {
    await api.submit({ assignment_id: assignmentId, body_text: text });
    setSubmitFor(null); setText(""); refresh();
  }

  if (!dash) return <Shell requiredRole="student"><div className="machine text-muted">loading…</div></Shell>;

  return (
    <Shell requiredRole="student">
      <h1 className="font-display text-3xl text-ink mb-1">My work</h1>
      <p className="text-muted mb-6">Your assignments, deadlines, and feedback.</p>

      {dash.assignments.length === 0 ? (
        <Card><p className="text-muted text-sm">No assignments yet.</p></Card>
      ) : (
        <div className="space-y-3">
          {dash.assignments.map((a) => (
            <Card key={a.assignment_id}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-display text-lg text-ink">{a.title}</div>
                  <div className="machine text-xs text-muted mt-0.5">
                    {a.due_at ? `due ${new Date(a.due_at).toLocaleDateString()}` : "no due date"}
                    {a.attempts > 0 && ` · ${a.attempts} attempt(s)`}
                  </div>
                </div>
                <div className="flex gap-2 items-center">
                  <Badge value={a.progress_state} />
                  {a.submission_state && <Badge value={a.submission_state} />}
                </div>
              </div>

              {a.submission_state !== "completed" && (
                <div className="flex gap-2 mt-3">
                  <Button variant="ghost" onClick={() => report(a.assignment_id, false)}>
                    I&apos;m working on it
                  </Button>
                  <Button variant="danger" onClick={() => report(a.assignment_id, true)}>
                    <Hand size={14} /> I&apos;m blocked
                  </Button>
                  <Button onClick={() => setSubmitFor(
                    submitFor === a.assignment_id ? null : a.assignment_id)}>
                    <Send size={14} /> Submit
                  </Button>
                </div>
              )}

              {submitFor === a.assignment_id && (
                <div className="mt-3">
                  <textarea value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="Type your submission or a note about the attached file…"
                    className="w-full px-2 py-1.5 rounded-md border border-line bg-surface
                               text-sm mb-2" rows={3} />
                  <Button onClick={() => submit(a.assignment_id)}>Send submission</Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Shell>
  );
}

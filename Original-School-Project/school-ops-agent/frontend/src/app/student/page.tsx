"use client";

import { useEffect, useRef, useState } from "react";
import { Hand, Paperclip, Send, X } from "lucide-react";
import { Badge, Button, Card, Shell } from "@/components/ui";
import { StudentDashboard, api } from "@/lib/api";

export default function StudentPage() {
  const [dash, setDash] = useState<StudentDashboard | null>(null);
  const [submitFor, setSubmitFor] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [attachedFile, setAttachedFile] = useState<{ id: string; name: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() { setDash(await api.studentDashboard()); }
  useEffect(() => { refresh().catch(() => {}); }, []);

  async function report(assignmentId: string, blocked: boolean) {
    await api.reportProgress({ assignment_id: assignmentId, blocked });
    refresh();
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    try {
      const res = await api.uploadSubmissionFile(file);
      setAttachedFile({ id: res.document_id, name: res.filename });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function submit(assignmentId: string) {
    setSubmitError(null);
    try {
      await api.submit({
        assignment_id: assignmentId,
        body_text: text || undefined,
        document_id: attachedFile?.id,
      });
      setSubmitFor(null); setText(""); setAttachedFile(null); refresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Submission failed");
    }
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
                  {a.subject && (
                    <div className="text-sm text-accent mt-0.5">{a.subject}</div>
                  )}
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

              {a.instructions && (
                <div className="mt-3 p-3 bg-paper rounded-md border border-line text-sm text-ink whitespace-pre-wrap">
                  {a.instructions}
                </div>
              )}

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
                <div className="mt-3 space-y-2">
                  <textarea value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="Type your answer, or attach a file below and add a note…"
                    className="w-full px-2 py-1.5 rounded-md border border-line bg-surface
                               text-sm" rows={3} />

                  {/* File attachment */}
                  <div className="flex items-center gap-2">
                    <input ref={fileRef} type="file" className="hidden"
                      accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                      onChange={handleFileChange} />
                    <button
                      onClick={() => fileRef.current?.click()}
                      disabled={uploading}
                      className="flex items-center gap-1.5 text-sm text-accent hover:underline disabled:opacity-50">
                      <Paperclip size={14} />
                      {uploading ? "Uploading…" : "Attach PDF or photo"}
                    </button>
                    {attachedFile && (
                      <span className="flex items-center gap-1 text-sm text-ok">
                        {attachedFile.name}
                        <button onClick={() => setAttachedFile(null)}
                          className="text-muted hover:text-blocked ml-1">
                          <X size={12} />
                        </button>
                      </span>
                    )}
                  </div>

                  {uploadError && <p className="text-blocked text-xs">{uploadError}</p>}
                  {submitError && <p className="text-blocked text-xs">{submitError}</p>}

                  <Button
                    onClick={() => submit(a.assignment_id)}
                    disabled={!text.trim() && !attachedFile}>
                    Send submission
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Shell>
  );
}

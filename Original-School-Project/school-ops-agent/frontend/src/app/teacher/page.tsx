"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, FileCheck, FileText, MessageSquare, Send, Sparkles, Upload } from "lucide-react";
import { Badge, Button, Card, Shell } from "@/components/ui";
import { DocumentDTO, TeacherDashboard, api, subscribeEvents } from "@/lib/api";

type PendingDoc = TeacherDashboard["documents_awaiting_review"][number];

export default function TeacherPage() {
  const [dash, setDash] = useState<TeacherDashboard | null>(null);
  const [classes, setClasses] = useState<{ id: string; name: string }[]>([]);

  // Manual assignment creation
  const [title, setTitle] = useState("");
  const [classId, setClassId] = useState("");
  const [due, setDue] = useState("");

  // Feedback
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState("");

  // Follow-up on blocked students
  const [followUpFor, setFollowUpFor] = useState<string | null>(null);  // "assignmentId:studentId"
  const [followUpNote, setFollowUpNote] = useState("");

  // Document upload
  const [uploadDocType, setUploadDocType] = useState("assignment_brief");
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<DocumentDTO | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Document review
  const [reviewingDocId, setReviewingDocId] = useState<string | null>(null);
  const [dueOverride, setDueOverride] = useState("");
  const [reviewClassId, setReviewClassId] = useState("");

  // AI review overrides (keyed by submission id) — lets us show a freshly-generated
  // review without waiting for a full dashboard refresh
  const [aiReviewCache, setAiReviewCache] = useState<
    Record<string, TeacherDashboard["submissions_to_review"][0]["ai_review"]>
  >({});
  const [generatingAiFor, setGeneratingAiFor] = useState<string | null>(null);

  async function refresh() {
    const [d, cls] = await Promise.all([api.teacherDashboard(), api.listClasses()]);
    setDash(d);
    setClasses(cls);
    if (cls[0] && !classId) setClassId(cls[0].id);
    if (cls[0] && !reviewClassId) setReviewClassId(cls[0].id);
  }

  useEffect(() => {
    refresh().catch(() => {});
    const unsub = subscribeEvents(() => { refresh().catch(() => {}); });
    return unsub;
  }, []);

  async function createAssignment() {
    if (!title.trim()) return;
    const a = await api.createAssignment({
      title: title.trim(), class_id: classId,
      due_at: due ? new Date(due).toISOString() : undefined,
    });
    await api.transitionAssignment(a.id, "published");
    await api.transitionAssignment(a.id, "active");
    setTitle(""); setDue(""); refresh();
  }

  async function sendFeedback(submissionId: string, decision: string) {
    await api.giveFeedback({
      submission_id: submissionId, body: feedbackText || "(no comment)", decision,
    });
    setFeedbackFor(null); setFeedbackText(""); refresh();
  }

  async function runReminders() { await api.runReminders(); refresh(); }

  async function sendFollowUp(assignmentId: string, studentId: string) {
    await api.teacherUnblock({ assignment_id: assignmentId, student_id: studentId, note: followUpNote });
    setFollowUpFor(null);
    setFollowUpNote("");
    refresh();
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setUploadError(null); setUploadResult(null);
    try {
      const result = await api.uploadDocument(uploadDocType, file);
      setUploadResult(result);
      refresh();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function approveAndCreate(doc: PendingDoc) {
    const overrides: Record<string, unknown> = {};
    if (dueOverride) overrides.due_at = new Date(dueOverride).toISOString();

    const approved = await api.approveDoc(doc.id, Object.keys(overrides).length ? overrides : undefined);

    if (doc.doc_type === "assignment_brief") {
      const parsed = approved.parsed || {};
      const a = await api.createAssignment({
        title: (parsed.title as string) || doc.filename,
        class_id: reviewClassId,
        subject: (parsed.subject as string) || undefined,
        instructions: (parsed.instructions as string) || undefined,
        due_at: (overrides.due_at as string) || (parsed.due_at as string) || undefined,
      });
      await api.transitionAssignment(a.id, "published");
      await api.transitionAssignment(a.id, "active");
    }

    setReviewingDocId(null);
    setDueOverride("");
    refresh();
  }

  async function doGenerateAiReview(submissionId: string) {
    setGeneratingAiFor(submissionId);
    try {
      const result = await api.generateAiReview(submissionId);
      setAiReviewCache((prev) => ({ ...prev, [submissionId]: result }));
    } catch {
      // ignore — the button will stay visible
    } finally {
      setGeneratingAiFor(null);
    }
  }

  async function approveOther(doc: PendingDoc) {
    await api.approveDoc(doc.id);
    setReviewingDocId(null);
    refresh();
  }

  if (!dash) return <Shell requiredRole="teacher"><div className="machine text-muted">loading…</div></Shell>;

  return (
    <Shell requiredRole="teacher">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-3xl text-ink">Operations</h1>
        <Button variant="ghost" onClick={runReminders}>
          <Bell size={14} /> Run reminder sweep
        </Button>
      </div>
      <p className="text-muted mb-6">What needs your attention, updating live.</p>

      {/* Row 1: attention cards */}
      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <Card title="Blocked students">
          {dash.blocked_students.length === 0 ? (
            <p className="text-muted text-sm">No one is blocked right now.</p>
          ) : (
            <ul className="space-y-2">
              {dash.blocked_students.map((b, i) => {
                const key = `${b.assignment_id}:${b.student_id}`;
                const isOpen = followUpFor === key;
                return (
                  <li key={i} className="border border-blocked/30 bg-blocked/5 rounded-md p-2">
                    <div className="flex items-start gap-2">
                      <AlertTriangle size={16} className="text-blocked mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <div className="text-sm font-medium text-ink">{b.student_name}</div>
                            {b.assignment_title && (
                              <div className="machine text-xs text-muted">{b.assignment_title}</div>
                            )}
                            {b.note && (
                              <div className="text-sm text-blocked mt-0.5">{b.note}</div>
                            )}
                            {b.teacher_note && (
                              <div className="text-xs text-muted mt-1 italic">
                                Your last note: {b.teacher_note}
                              </div>
                            )}
                          </div>
                          <Button variant="ghost"
                            onClick={() => {
                              setFollowUpFor(isOpen ? null : key);
                              setFollowUpNote("");
                            }}>
                            {isOpen ? "Cancel" : "Follow up"}
                          </Button>
                        </div>

                        {isOpen && (
                          <div className="mt-2">
                            <textarea
                              value={followUpNote}
                              onChange={(e) => setFollowUpNote(e.target.value)}
                              placeholder="Write a note to help unblock the student…"
                              className="w-full px-2 py-1.5 rounded-md border border-line
                                         bg-surface text-sm mb-2"
                              rows={2} />
                            <Button onClick={() => sendFollowUp(b.assignment_id, b.student_id)}>
                              Send note &amp; unblock
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Submissions to review">
          {dash.submissions_to_review.length === 0 ? (
            <p className="text-muted text-sm">Nothing waiting for review.</p>
          ) : (
            <ul className="space-y-2">
              {dash.submissions_to_review.map((s) => (
                <li key={s.id} className="border border-line rounded-md p-3 space-y-2">
                  {/* Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium text-ink">{s.student_name}</div>
                      {s.assignment_title && (
                        <div className="machine text-xs text-muted">{s.assignment_title}</div>
                      )}
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="machine text-xs text-muted">attempt {s.attempt}</span>
                        <Badge value={s.state} />
                        {s.submitted_at && (
                          <span className="machine text-xs text-muted">
                            {new Date(s.submitted_at).toLocaleString(undefined, {
                              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                            })}
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => setFeedbackFor(feedbackFor === s.id ? null : s.id)}
                      className="text-sm text-accent hover:underline shrink-0">
                      {feedbackFor === s.id ? "Close" : "Review"}
                    </button>
                  </div>

                  {/* Submission content — always visible */}
                  {s.body_text && (
                    <div className="bg-paper border border-line rounded p-2">
                      <div className="flex items-center gap-1.5 machine text-xs text-muted mb-1">
                        <MessageSquare size={11} /> Student answer
                      </div>
                      <p className="text-sm text-ink whitespace-pre-wrap">{s.body_text}</p>
                    </div>
                  )}
                  {s.document_filename && s.document_id && (
                    <a
                      href={api.documentFileUrl(s.document_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-sm text-accent hover:underline">
                      <FileText size={14} />
                      <span>{s.document_filename}</span>
                      <span className="machine text-xs text-muted">(open file)</span>
                    </a>
                  )}
                  {!s.body_text && !s.document_filename && (
                    <p className="text-xs text-muted italic">No content submitted.</p>
                  )}

                  {/* Prior feedback history */}
                  {s.prior_feedback.length > 0 && (
                    <div className="border-t border-line pt-2 space-y-1">
                      <div className="machine text-xs text-muted mb-1">Feedback history</div>
                      {s.prior_feedback.map((f, i) => (
                        <div key={i} className="text-xs bg-surface rounded p-1.5 border border-line">
                          <span className={`machine mr-1.5 ${f.decision === "complete" ? "text-ok" : "text-blocked"}`}>
                            [{f.decision ?? "note"}]
                          </span>
                          {f.body}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* AI review panel */}
                  {(() => {
                    const aiReview = aiReviewCache[s.id] ?? s.ai_review;
                    if (!aiReview) {
                      return (
                        <button
                          onClick={() => doGenerateAiReview(s.id)}
                          disabled={generatingAiFor === s.id}
                          className="flex items-center gap-1.5 text-xs text-accent hover:underline disabled:opacity-50">
                          <Sparkles size={11} />
                          {generatingAiFor === s.id ? "Generating AI review…" : "Generate AI review"}
                        </button>
                      );
                    }
                    return (
                      <div className="border border-accent/30 bg-accent/5 rounded-md p-2 space-y-1.5">
                        <div className="flex items-center gap-1.5 machine text-xs text-accent">
                          <Sparkles size={11} /> AI pre-assessment
                          <span className="ml-auto text-muted">
                            confidence {Math.round(aiReview.confidence * 100)}%
                          </span>
                        </div>
                        <p className="text-xs text-ink">{aiReview.summary}</p>
                        {aiReview.strengths.length > 0 && (
                          <div>
                            <div className="machine text-[10px] text-ok mb-0.5">Strengths</div>
                            <ul className="list-disc pl-3 space-y-0.5">
                              {aiReview.strengths.map((t, i) => (
                                <li key={i} className="text-xs text-ink">{t}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {aiReview.gaps.length > 0 && (
                          <div>
                            <div className="machine text-[10px] text-blocked mb-0.5">Gaps</div>
                            <ul className="list-disc pl-3 space-y-0.5">
                              {aiReview.gaps.map((t, i) => (
                                <li key={i} className="text-xs text-ink">{t}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div className="flex items-center gap-2 pt-1">
                          <span className="machine text-[10px] text-muted">AI suggests:</span>
                          <span className={`machine text-[10px] font-medium ${
                            aiReview.suggested_decision === "complete" ? "text-ok" : "text-blocked"
                          }`}>
                            {aiReview.suggested_decision === "complete" ? "Mark complete" : "Request revision"}
                          </span>
                          <button
                            onClick={() => {
                              setFeedbackFor(s.id);
                              setFeedbackText(aiReview.suggested_feedback);
                            }}
                            className="ml-auto text-xs text-accent hover:underline">
                            Use AI draft
                          </button>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Feedback panel */}
                  {feedbackFor === s.id && (
                    <div className="border-t border-line pt-2">
                      <textarea value={feedbackText}
                        onChange={(e) => setFeedbackText(e.target.value)}
                        placeholder="Write feedback for the student… or use the AI draft above."
                        className="w-full px-2 py-1.5 rounded-md border border-line
                                   bg-surface text-sm mb-2" rows={3} />
                      <div className="flex gap-2">
                        <Button variant="ghost" onClick={() => sendFeedback(s.id, "revision")}>
                          Request revision
                        </Button>
                        <Button onClick={() => sendFeedback(s.id, "complete")}>
                          <FileCheck size={14} /> Mark complete
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* Row 2: upload + manual create */}
      <div className="grid grid-cols-2 gap-4 mt-4 max-[900px]:grid-cols-1">
        {/* Upload document → pipeline */}
        <Card title="Upload document">
          <select
            value={uploadDocType}
            onChange={(e) => setUploadDocType(e.target.value)}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface text-sm mb-2">
            <option value="assignment_brief">Assignment brief</option>
            <option value="class_roster">Class roster</option>
            <option value="school_policy">School policy</option>
            <option value="other">Other</option>
          </select>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".pdf,.docx,.csv,.txt,.png,.jpg,.jpeg"
            onChange={handleFileUpload}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            <Upload size={14} /> {uploading ? "Uploading…" : "Choose file & upload"}
          </Button>

          {uploadError && (
            <p className="text-sm text-blocked mt-2">{uploadError}</p>
          )}

          {uploadResult && (
            <div className="mt-3 border border-line rounded-md p-2 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm truncate flex-1">{uploadResult.filename}</span>
                <Badge value={uploadResult.review_state} />
              </div>
              {uploadResult.confidence != null && (
                <p className="machine text-xs text-muted">
                  confidence {Math.round(uploadResult.confidence * 100)}%
                </p>
              )}
              {(uploadResult.clarifying_questions ?? []).length > 0 && (
                <div className="bg-blocked/5 border border-blocked/20 rounded p-2 mt-1">
                  <p className="machine text-xs text-blocked mb-1">needs clarification</p>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {uploadResult.clarifying_questions!.map((q, i) => (
                      <li key={i} className="text-sm text-ink">{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              {uploadResult.review_state === "parsed" && (
                <p className="text-xs text-muted">
                  Parsed — see "Documents awaiting your approval" below to review.
                </p>
              )}
            </div>
          )}

          {/* Pipeline steps legend */}
          <div className="mt-4 border-t border-line pt-3">
            <p className="machine text-xs text-muted mb-2">pipeline</p>
            <ol className="space-y-1">
              {[
                "Extract text (pypdf / docx / csv)",
                "Injection scan + delimiter wrap",
                "LLM parse → JSON schema",
                "Pydantic validate",
                "Human review & approve",
              ].map((step, i) => (
                <li key={i} className="flex items-center gap-2 text-xs text-muted">
                  <span className="machine text-[10px] w-4 text-center shrink-0">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        </Card>

        {/* Manual assignment creation */}
        <Card title="Create assignment">
          <input value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Assignment title"
            className="w-full px-3 py-2 rounded-md border border-line bg-surface mb-2" />
          <div className="flex gap-2 mb-2">
            <select value={classId} onChange={(e) => setClassId(e.target.value)}
              className="flex-1 px-3 py-2 rounded-md border border-line bg-surface text-sm">
              {classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input type="datetime-local" value={due}
              onChange={(e) => setDue(e.target.value)}
              className="px-3 py-2 rounded-md border border-line bg-surface text-sm" />
          </div>
          <Button onClick={createAssignment}><Send size={14} /> Publish & activate</Button>
        </Card>
      </div>

      {/* Row 3: document review (full width) */}
      <div className="mt-4">
        <Card title="Documents awaiting your approval">
          {dash.documents_awaiting_review.length === 0 ? (
            <p className="text-muted text-sm">No documents to review.</p>
          ) : (
            <ul className="space-y-3">
              {dash.documents_awaiting_review.map((d) => {
                const isReviewing = reviewingDocId === d.id;
                const parsed = (d.parsed ?? {}) as Record<string, string | null | undefined>;
                const hasDue = Boolean(parsed.due_at);
                const isAssignmentBrief = d.doc_type === "assignment_brief";

                return (
                  <li key={d.id} className="border border-line rounded-md p-3">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-sm font-medium truncate">{d.filename}</span>
                        <span className="machine text-xs text-muted shrink-0">
                          {d.doc_type.replace("_", " ")}
                        </span>
                      </div>
                      <Badge value={d.review_state} />
                    </div>

                    {/* Parsed preview (always shown) */}
                    {isAssignmentBrief && parsed.title && (
                      <div className="bg-surface border border-line rounded p-2 mb-2 space-y-1">
                        <p className="text-sm font-medium">{parsed.title}</p>
                        {parsed.subject && (
                          <p className="machine text-xs text-muted">
                            subject: {parsed.subject}
                          </p>
                        )}
                        {hasDue ? (
                          <p className="machine text-xs text-muted">
                            due: {new Date(parsed.due_at!).toLocaleString()}
                          </p>
                        ) : (
                          <p className="machine text-xs text-blocked">due: not found</p>
                        )}
                      </div>
                    )}

                    {/* Clarifying questions */}
                    {d.clarifying_questions.length > 0 && (
                      <div className="bg-blocked/5 border border-blocked/20 rounded p-2 mb-2">
                        <p className="machine text-xs text-blocked mb-1">needs clarification</p>
                        <ul className="list-disc pl-4 space-y-0.5">
                          {d.clarifying_questions.map((q, i) => (
                            <li key={i} className="text-sm text-ink">{q}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Review panel (expanded) */}
                    {isReviewing ? (
                      <div className="space-y-2 mt-1">
                        {isAssignmentBrief && (
                          <>
                            {!hasDue && (
                              <div>
                                <label className="machine text-xs text-muted block mb-1">
                                  Due date <span className="text-blocked">*</span>
                                </label>
                                <input
                                  type="datetime-local"
                                  value={dueOverride}
                                  onChange={(e) => setDueOverride(e.target.value)}
                                  className="w-full px-3 py-1.5 rounded-md border border-line
                                             bg-surface text-sm"
                                />
                              </div>
                            )}
                            <div>
                              <label className="machine text-xs text-muted block mb-1">
                                Assign to class
                              </label>
                              <select
                                value={reviewClassId}
                                onChange={(e) => setReviewClassId(e.target.value)}
                                className="w-full px-3 py-1.5 rounded-md border border-line
                                           bg-surface text-sm">
                                {classes.map((c) => (
                                  <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                              </select>
                            </div>
                          </>
                        )}
                        <div className="flex gap-2">
                          <Button variant="ghost" onClick={async () => {
                            await api.rejectDoc(d.id);
                            setReviewingDocId(null);
                            refresh();
                          }}>
                            Reject
                          </Button>
                          <Button onClick={() =>
                            isAssignmentBrief ? approveAndCreate(d) : approveOther(d)
                          }>
                            <FileCheck size={14} />
                            {isAssignmentBrief ? "Approve & create assignment" : "Approve"}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <Button variant="ghost" onClick={async () => {
                          await api.rejectDoc(d.id); refresh();
                        }}>
                          Reject
                        </Button>
                        <Button onClick={() => {
                          setReviewingDocId(d.id);
                          setDueOverride("");
                          if (classes[0]) setReviewClassId(classes[0].id);
                        }}>
                          Review
                        </Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </Shell>
  );
}

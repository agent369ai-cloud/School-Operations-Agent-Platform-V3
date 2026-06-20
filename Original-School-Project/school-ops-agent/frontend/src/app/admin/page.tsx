"use client";

import { useEffect, useState } from "react";
import { Copy, Plus, Trash2, Upload } from "lucide-react";
import { Badge, Button, Card, Shell } from "@/components/ui";
import { DocumentDTO, api, subscribeEvents } from "@/lib/api";

export default function AdminPage() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [classes, setClasses] = useState<{ id: string; name: string }[]>([]);
  const [docs, setDocs] = useState<DocumentDTO[]>([]);
  const [newClass, setNewClass] = useState("");
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteRole, setInviteRole] = useState<"teacher" | "student" | "guardian">("teacher");
  const [inviteClass, setInviteClass] = useState("");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [classError, setClassError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function refresh() {
    const [d, cls, dl] = await Promise.all([
      api.adminDashboard(), api.listClasses(), api.listDocuments(),
    ]);
    setCounts(d.counts); setClasses(cls); setDocs(dl);
    if (cls[0] && !inviteClass) setInviteClass(cls[0].id);
  }
  useEffect(() => {
    refresh().catch(() => {});
    // Re-fetch counts whenever a live event comes in (document uploaded, class added, etc.)
    const unsub = subscribeEvents(() => { refresh().catch(() => {}); });
    return unsub;
  }, []);

  async function deleteClass(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    setClassError(null);
    try {
      await api.deleteClass(id);
      refresh();
    } catch (e) {
      setClassError(e instanceof Error ? e.message : "Failed to delete class");
    }
  }

  async function addClass() {
    if (!newClass.trim()) return;
    setClassError(null);
    try {
      await api.createClass({ name: newClass.trim() });
      setNewClass("");
      refresh();
    } catch (e) {
      setClassError(e instanceof Error ? e.message : "Failed to create class");
    }
  }

  async function makeInvite() {
    setInviteError(null);
    setInviteToken(null);
    try {
      const r = await api.createInvite({
        role: inviteRole,
        class_id: inviteRole !== "guardian" ? inviteClass : undefined,
      });
      setInviteToken(r.token);
    } catch (e) {
      setInviteError(e instanceof Error ? e.message : "Failed to create invite");
    }
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>, docType: string) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    try {
      await api.uploadDocument(docType, file);
      refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    }
    // Reset the input so the same file can be re-uploaded after a fix.
    e.target.value = "";
  }

  return (
    <Shell requiredRole="admin">
      <h1 className="font-display text-3xl text-ink mb-1">School overview</h1>
      <p className="text-muted mb-6">Set up classes, invite people, review parsed documents.</p>

      {/* Counts: numbers in mono so they read as live tallies, not hero stats. */}
      <div className="grid grid-cols-3 gap-3 mb-6 max-[700px]:grid-cols-2">
        {Object.entries(counts).map(([k, v]) => (
          <div key={k} className="bg-surface border border-line rounded-lg px-4 py-3">
            <div className="machine text-2xl text-ink">{v}</div>
            <div className="text-sm text-muted">{k.replace(/_/g, " ")}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <Card title="Classes">
          <ul className="mb-3 space-y-1">
            {classes.map((c) => (
              <li key={c.id} className="flex items-center justify-between text-sm group">
                <span>{c.name}</span>
                <div className="flex items-center gap-2">
                  <span className="machine text-muted">{c.id.slice(0, 8)}</span>
                  <button
                    onClick={() => deleteClass(c.id, c.name)}
                    title="Delete class"
                    className="text-muted hover:text-blocked opacity-0 group-hover:opacity-100
                               transition-opacity">
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
            {classes.length === 0 && <li className="text-muted text-sm">No classes yet.</li>}
          </ul>
          <div className="flex gap-2">
            <input value={newClass} onChange={(e) => setNewClass(e.target.value)}
              placeholder="e.g. Grade 7-A"
              onKeyDown={(e) => e.key === "Enter" && addClass()}
              className="flex-1 px-3 py-1.5 rounded-md border border-line bg-surface text-sm" />
            <Button onClick={addClass}><Plus size={14} /> Add</Button>
          </div>
          {classError && <p className="text-blocked text-sm mt-2">{classError}</p>}
        </Card>

        <Card title="Invite a person">
          <div className="flex gap-2 mb-3">
            <select value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
              className="px-3 py-1.5 rounded-md border border-line bg-surface text-sm">
              <option value="teacher">Teacher</option>
              <option value="student">Student</option>
              <option value="guardian">Guardian</option>
            </select>
            {inviteRole !== "guardian" && (
              <select value={inviteClass} onChange={(e) => setInviteClass(e.target.value)}
                disabled={classes.length === 0}
                className="flex-1 px-3 py-1.5 rounded-md border border-line bg-surface text-sm disabled:opacity-50">
                {classes.length === 0
                  ? <option value="">— add a class first —</option>
                  : classes.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
            <Button onClick={makeInvite} disabled={inviteRole !== "guardian" && !inviteClass}>Create</Button>
          </div>
          {inviteError && <p className="text-blocked text-sm mb-2">{inviteError}</p>}
          {inviteToken && (
            <div className="bg-paper border border-line rounded-md p-3">
              <div className="text-sm text-muted mb-1">
                Share this code (shown once). They accept it at <b>/link</b>.
              </div>
              <div className="flex items-center gap-2">
                <code className="machine text-ink break-all flex-1">{inviteToken}</code>
                <button onClick={() => navigator.clipboard?.writeText(inviteToken)}
                  className="text-muted hover:text-accent"><Copy size={15} /></button>
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Documents awaiting review"
          action={
            <div className="flex gap-2">
              <label className="cursor-pointer text-sm text-accent flex items-center gap-1">
                <Upload size={14} /> Roster
                <input type="file" className="hidden" accept=".csv,.txt"
                  onChange={(e) => upload(e, "class_roster")} />
              </label>
              <label className="cursor-pointer text-sm text-accent flex items-center gap-1">
                <Upload size={14} /> Brief
                <input type="file" className="hidden" accept=".pdf,.docx,.txt"
                  onChange={(e) => upload(e, "assignment_brief")} />
              </label>
            </div>
          }>
          {uploadError && <p className="text-blocked text-sm mb-2">{uploadError}</p>}
          <DocReview docs={docs} onChange={refresh} />
        </Card>
      </div>
    </Shell>
  );
}

// Reusable review panel: shows extracted values + clarifying questions before commit.
function DocReview({ docs, onChange }: { docs: DocumentDTO[]; onChange: () => void }) {
  if (docs.length === 0) return <p className="text-muted text-sm">Nothing to review.</p>;
  return (
    <ul className="space-y-3">
      {docs.map((d) => (
        <li key={d.id} className="border border-line rounded-md p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{d.filename}</span>
              <Badge value={d.review_state} />
              {d.confidence != null && (
                <span className="machine text-muted">conf {d.confidence}</span>
              )}
            </div>
            {(d.review_state === "parsed" || d.review_state === "needs_clarification") && (
              <div className="flex gap-2">
                <Button variant="ghost" onClick={async () => { await api.rejectDoc(d.id); onChange(); }}>
                  Reject
                </Button>
                <Button onClick={async () => { await api.approveDoc(d.id); onChange(); }}>
                  Approve
                </Button>
              </div>
            )}
          </div>
          {d.parsed && (
            <pre className="machine text-xs bg-paper rounded p-2 overflow-x-auto mb-2">
              {JSON.stringify(d.parsed, null, 2)}
            </pre>
          )}
          {d.clarifying_questions && d.clarifying_questions.length > 0 && (
            <div>
              <div className="text-sm text-blocked mb-1">Needs clarification:</div>
              <ul className="list-disc pl-5 text-sm text-ink">
                {d.clarifying_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

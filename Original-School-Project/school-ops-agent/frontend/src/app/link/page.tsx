"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, saveSession } from "@/lib/api";

function LinkForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [token, setToken] = useState(params.get("token") || "");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError(null);
    try {
      const s = await api.acceptInvite({
        token, full_name: fullName,
        email: email || undefined,
        password: password || undefined,
      });
      saveSession(s);
      router.replace(s.role === "admin" ? "/admin"
        : s.role === "teacher" ? "/teacher"
        : s.role === "guardian" ? "/guardian"
        : "/student");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not accept invite");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="w-full max-w-md">
        <h1 className="font-display text-2xl text-ink mb-1">Accept your invite</h1>
        <p className="text-muted text-sm mb-6">
          Paste the code from your invite. Students and guardians can leave the
          password blank.
        </p>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">Invite code</span>
          <input value={token} onChange={(e) => setToken(e.target.value)}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface machine" />
        </label>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">Your name</span>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        <label className="block mb-4">
          <span className="block text-sm text-muted mb-1">Password</span>
          <input type="password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="min 8 characters"
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        {error && <p className="text-blocked text-sm mb-3">{error}</p>}
        <button onClick={submit} disabled={busy || !token || !fullName}
          className="w-full bg-accent text-paper py-2 rounded-md font-medium
                     hover:bg-accent-dark disabled:opacity-50">
          {busy ? "Linking…" : "Accept invite"}
        </button>
      </div>
    </div>
  );
}

export default function LinkPage() {
  return (
    <Suspense>
      <LinkForm />
    </Suspense>
  );
}

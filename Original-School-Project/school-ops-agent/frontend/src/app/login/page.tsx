"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, saveSession } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@lincoln.test");
  const [password, setPassword] = useState("Password123!");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError(null);
    try {
      const s = await api.login({ email, password });
      saveSession(s);
      router.replace(
        s.role === "admin" ? "/admin"
          : s.role === "teacher" ? "/teacher"
          : s.role === "guardian" ? "/guardian"
          : "/student"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen grid grid-cols-2 max-[800px]:grid-cols-1">
      {/* Left: the ledger thesis — a quiet, monospace operational tagline. */}
      <div className="bg-ink text-paper flex flex-col justify-between p-10 max-[800px]:hidden">
        <div className="font-display text-2xl">School Ops</div>
        <div>
          <p className="font-display text-3xl leading-tight mb-4">
            Every action the agent takes, on the record.
          </p>
          <p className="machine text-paper/60 leading-relaxed">
            assignments · submissions · reminders<br />
            parsed docs await your approval<br />
            nothing happens without an audit line
          </p>
        </div>
        <div className="machine text-paper/40">school operations console</div>
      </div>

      {/* Right: sign in */}
      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <h1 className="font-display text-2xl text-ink mb-1">Sign in</h1>
          <p className="text-muted text-sm mb-6">Staff accounts use email + password.</p>
          <label className="block mb-3">
            <span className="block text-sm text-muted mb-1">Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
          </label>
          <label className="block mb-4">
            <span className="block text-sm text-muted mb-1">Password</span>
            <input type="password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
          </label>
          {error && <p className="text-blocked text-sm mb-3">{error}</p>}
          <button onClick={submit} disabled={busy}
            className="w-full bg-accent text-paper py-2 rounded-md font-medium
                       hover:bg-accent-dark disabled:opacity-50">
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <div className="mt-6 text-sm text-muted">
            New school?{" "}
            <a href="/register" className="text-accent hover:underline">Register</a>
            {"  ·  "}
            Have an invite?{" "}
            <a href="/link" className="text-accent hover:underline">Accept it</a>
          </div>
        </div>
      </div>
    </div>
  );
}

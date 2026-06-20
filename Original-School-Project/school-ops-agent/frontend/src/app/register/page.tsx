"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, saveSession } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [f, setF] = useState({
    school_name: "", admin_name: "", admin_email: "", admin_password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set(k: keyof typeof f) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setF({ ...f, [k]: e.target.value });
  }

  async function submit() {
    setBusy(true); setError(null);
    try {
      const s = await api.registerSchool(f);
      saveSession(s);
      router.replace("/admin");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="w-full max-w-md">
        <h1 className="font-display text-2xl text-ink mb-1">Register a school</h1>
        <p className="text-muted text-sm mb-6">
          This creates your school and its first admin account.
        </p>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">School name</span>
          <input value={f.school_name} onChange={set("school_name")}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">Your name</span>
          <input value={f.admin_name} onChange={set("admin_name")}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        <label className="block mb-3">
          <span className="block text-sm text-muted mb-1">Email</span>
          <input type="email" value={f.admin_email} onChange={set("admin_email")}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        <label className="block mb-4">
          <span className="block text-sm text-muted mb-1">Password (min 8 chars)</span>
          <input type="password" value={f.admin_password} onChange={set("admin_password")}
            className="w-full px-3 py-2 rounded-md border border-line bg-surface" />
        </label>
        {error && <p className="text-blocked text-sm mb-3">{error}</p>}
        <button onClick={submit} disabled={busy}
          className="w-full bg-accent text-paper py-2 rounded-md font-medium
                     hover:bg-accent-dark disabled:opacity-50">
          {busy ? "Creating…" : "Create school"}
        </button>
        <div className="mt-6 text-sm text-muted">
          Already have an account?{" "}
          <a href="/login" className="text-accent hover:underline">Sign in</a>
        </div>
      </div>
    </div>
  );
}

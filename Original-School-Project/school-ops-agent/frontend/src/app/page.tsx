"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { loadSession } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    const s = loadSession();
    if (!s) { router.replace("/login"); return; }
    router.replace(s.role === "admin" ? "/admin"
      : s.role === "teacher" ? "/teacher" : "/student");
  }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="machine text-muted">routing…</div>
    </div>
  );
}

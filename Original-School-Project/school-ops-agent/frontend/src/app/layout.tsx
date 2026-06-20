import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "School Ops — School Operations Agent Platform",
  description: "Staff console for assignments, submissions, reminders, and audit.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

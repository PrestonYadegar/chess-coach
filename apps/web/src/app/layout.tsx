import "./globals.css";
import type { Metadata } from "next";
import JobStatusWidget from "./JobStatusWidget";

export const metadata: Metadata = {
  title: "chess-coach",
  description: "Free, self-hostable chess improvement platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        {children}
        <JobStatusWidget />
      </body>
    </html>
  );
}

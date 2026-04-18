"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const name = username.trim();
    if (!name) return;

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/players/${encodeURIComponent(name)}/sync`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Sync failed (${res.status})`);
      }
      router.push(`/players/${encodeURIComponent(name)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-4xl font-bold tracking-tight">chess-coach</h1>
      <p className="mt-4 text-neutral-400">
        Pull your games. Find your mistakes. Drill them. Free forever.
      </p>

      <form onSubmit={handleSubmit} className="mt-12 flex gap-3">
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Chess.com username"
          disabled={loading}
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-3 text-neutral-100 placeholder-neutral-500 focus:border-neutral-500 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !username.trim()}
          className="rounded-lg bg-white px-6 py-3 text-sm font-semibold text-neutral-950 transition hover:bg-neutral-200 disabled:opacity-40"
        >
          {loading ? "Syncing…" : "Go"}
        </button>
      </form>

      {error && (
        <p className="mt-4 text-sm text-red-400">{error}</p>
      )}

      {loading && (
        <p className="mt-4 text-sm text-neutral-500">
          Importing games from Chess.com — this may take a moment for large archives…
        </p>
      )}
    </main>
  );
}

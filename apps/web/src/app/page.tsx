"use client";

import { useState, FormEvent, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Progress = {
  archive: string;
  index: number;
  total: number;
  gamesInserted: number;
};

type PlayerRow = {
  username: string;
  last_synced_at: string | null;
  games: number;
  analyzed: number;
};

export default function Home() {
  const [username, setUsername] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [players, setPlayers] = useState<PlayerRow[] | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const router = useRouter();

  useEffect(() => {
    fetch(`${API_URL}/players`)
      .then((r) => (r.ok ? r.json() : { players: [] }))
      .then((d) => setPlayers(d.players ?? []))
      .catch(() => setPlayers([]));
  }, []);

  function closeStream() {
    esRef.current?.close();
    esRef.current = null;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const name = username.trim();
    if (!name) return;

    setLoading(true);
    setError(null);
    setProgress(null);

    const url = `${API_URL}/players/${encodeURIComponent(name)}/sync/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (evt) => {
      let data: any;
      try {
        data = JSON.parse(evt.data);
      } catch {
        return;
      }
      if (data.type === "start") {
        setProgress({
          archive: "",
          index: 0,
          total: data.archives ?? 0,
          gamesInserted: 0,
        });
      } else if (data.type === "archive_done") {
        setProgress({
          archive: data.archive,
          index: data.index + 1,
          total: data.archives_total,
          gamesInserted: data.games_inserted_total,
        });
      } else if (data.type === "archive_error") {
        // Non-fatal; surface but keep going.
        setError(`Skipped ${data.archive}: ${data.message}`);
      } else if (data.type === "done") {
        closeStream();
        router.push(`/players/${encodeURIComponent(name)}`);
      } else if (data.type === "error") {
        closeStream();
        setError(data.message ?? "Sync failed");
        setLoading(false);
      }
    };

    es.onerror = () => {
      // Only treat as error if we never finished.
      if (esRef.current) {
        closeStream();
        setError("Connection to sync stream lost");
        setLoading(false);
      }
    };
  }

  const pct =
    progress && progress.total
      ? Math.min(100, Math.round((progress.index / progress.total) * 100))
      : 0;

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

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {loading && (
        <div className="mt-8 space-y-3">
          <div className="h-2 w-full overflow-hidden rounded-full bg-neutral-800">
            <div
              className="h-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-sm text-neutral-400">
            <span>
              {progress
                ? progress.archive
                  ? `Imported ${progress.archive} — ${progress.index}/${progress.total} archives`
                  : `Found ${progress.total} archives, starting…`
                : "Connecting to Chess.com…"}
            </span>
            <span className="tabular-nums text-neutral-500">
              {progress?.gamesInserted ?? 0} games
            </span>
          </div>
        </div>
      )}

      {!loading && players && players.length > 0 && (
        <div className="mt-12">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Recently synced
          </h2>
          <ul className="divide-y divide-neutral-800 rounded-xl border border-neutral-800 bg-neutral-950">
            {players.map((p) => (
              <li key={p.username}>
                <Link
                  href={`/players/${encodeURIComponent(p.username)}`}
                  className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-neutral-900"
                >
                  <span className="font-medium text-neutral-200">
                    {p.username}
                  </span>
                  <span className="text-xs tabular-nums text-neutral-500">
                    {p.analyzed}/{p.games} analyzed
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </main>
  );
}

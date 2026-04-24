"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { API_URL } from "@/lib/api";

/**
 * Re-sync in place: opens the SSE sync stream (incremental by default — the
 * backend only re-fetches months since the last sync) and shows a spinner.
 * On completion it refreshes the server component so new games appear without
 * leaving the page.
 */
export default function ResyncButton({ username }: { username: string }) {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inserted, setInserted] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  // Clean up the stream if the component unmounts mid-sync.
  useEffect(() => () => esRef.current?.close(), []);

  function start() {
    if (syncing) return;
    setSyncing(true);
    setError(null);
    setInserted(0);

    const url = `${API_URL}/players/${encodeURIComponent(username)}/sync/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (evt) => {
      let data: any;
      try {
        data = JSON.parse(evt.data);
      } catch {
        return;
      }
      if (data.type === "archive_done") {
        setInserted(data.games_inserted_total ?? 0);
      } else if (data.type === "done") {
        finish();
        router.refresh();
      } else if (data.type === "error") {
        finish();
        setError(data.message ?? "Sync failed");
      }
    };
    es.onerror = () => {
      finish();
      setError("Sync connection lost");
    };
  }

  function finish() {
    esRef.current?.close();
    esRef.current = null;
    setSyncing(false);
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={start}
        disabled={syncing}
        className="flex items-center gap-2 rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100 disabled:opacity-70"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`}
          aria-hidden="true"
        >
          <path d="M3 2v6h6" />
          <path d="M21 12A9 9 0 0 0 6 5.3L3 8" />
          <path d="M21 22v-6h-6" />
          <path d="M3 12a9 9 0 0 0 15 6.7l3-2.7" />
        </svg>
        {syncing
          ? inserted > 0
            ? `Syncing… +${inserted}`
            : "Syncing…"
          : "Re-sync"}
      </button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface JobSnapshot {
  id: string;
  username: string;
  status: "running" | "done" | "error" | "cancelled";
  total: number;
  analyzed: number;
  plies_total: number;
  errors: number;
  last_label: string;
  error_message: string | null;
  current_ply?: number | null;
  current_game_plies?: number | null;
}

// A global, app-wide progress pill (bottom-right) for the background analysis
// job. It discovers a running job via GET /jobs/active and tails its SSE
// stream. When no job is running but the player you're viewing still has
// unanalyzed games, it shows an idle "Analyze" pill so you can start one from
// anywhere (e.g. after restarting the API, which clears the job registry).
export default function JobStatusWidget() {
  const router = useRouter();
  const pathname = usePathname();
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const streamedIdRef = useRef<string | null>(null);

  // Username from the current route (/players/<username>/...), used for the
  // idle state when there's no job to attach to.
  const m = pathname?.match(/^\/players\/([^/]+)/);
  const pageUsername = m ? decodeURIComponent(m[1]) : null;

  const closeStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    streamedIdRef.current = null;
  }, []);

  const attachStream = useCallback(
    (snap: JobSnapshot) => {
      if (streamedIdRef.current === snap.id) return;
      closeStream();
      streamedIdRef.current = snap.id;
      const es = new EventSource(`${API_URL}/jobs/${snap.id}/stream`);
      esRef.current = es;
      es.onmessage = (evt) => {
        let data: { type: string; [k: string]: unknown };
        try {
          data = JSON.parse(evt.data);
        } catch {
          return;
        }
        if (data.type === "snapshot") {
          setJob((p) => ({ ...(p as JobSnapshot), ...(data as object) } as JobSnapshot));
        } else if (data.type === "ply_progress") {
          setJob((p) =>
            p
              ? {
                  ...p,
                  plies_total: Number(data.plies_done ?? p.plies_total),
                  current_ply: Number(data.ply ?? 0),
                  current_game_plies: Number(data.game_plies ?? 0),
                  last_label: String(data.label ?? p.last_label),
                }
              : p
          );
        } else if (data.type === "game_done") {
          setJob((p) =>
            p
              ? {
                  ...p,
                  total: Number(data.games_total ?? p.total),
                  analyzed: Number(data.analyzed ?? p.analyzed),
                  plies_total: Number(data.plies_total ?? p.plies_total),
                  last_label: String(data.label ?? p.last_label),
                }
              : p
          );
        } else if (data.type === "game_error") {
          setJob((p) => (p ? { ...p, errors: p.errors + 1 } : p));
        } else if (
          data.type === "done" ||
          data.type === "cancelled" ||
          data.type === "error"
        ) {
          setJob((p) =>
            p ? { ...p, status: data.type === "error" ? "error" : (data.type as JobSnapshot["status"]) } : p
          );
          closeStream();
        }
      };
      es.onerror = () => closeStream();
    },
    [closeStream]
  );

  // Start/resume analysis for a player using their saved auto-analyze settings.
  // only_unanalyzed continues from where it left off.
  const startAnalysis = useCallback(
    async (username: string) => {
      const u = encodeURIComponent(username);
      setBusy(true);
      try {
        const s = await fetch(`${API_URL}/players/${u}/settings`)
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        const res = await fetch(`${API_URL}/players/${u}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            depth: s?.auto_depth ?? 18,
            workers: s?.auto_workers ?? 4,
            limit: 1000,
            only_unanalyzed: true,
          }),
        });
        if (res.ok) {
          const snap: JobSnapshot = await res.json();
          setStopping(false);
          setJob(snap);
          attachStream(snap);
        }
      } finally {
        setBusy(false);
      }
    },
    [attachStream]
  );

  const stop = useCallback(async () => {
    if (!job) return;
    // Cancellation only takes effect at the next ply/game boundary, so show a
    // "Stopping…" state until the stream reports a terminal status.
    setStopping(true);
    try {
      await fetch(`${API_URL}/jobs/${job.id}/stop`, { method: "POST" });
    } catch {
      // stream will reflect the cancelled state when it lands
    }
  }, [job]);

  // Clear the stopping state once the job is no longer running.
  useEffect(() => {
    if (job && job.status !== "running") setStopping(false);
  }, [job]);

  // Poll for an active job. Cheap (one GET) and resilient to API restarts.
  useEffect(() => {
    let cancelledHook = false;
    const poll = () => {
      fetch(`${API_URL}/jobs/active`)
        .then((r) => (r.ok ? r.json() : null))
        .then((snap: JobSnapshot | null) => {
          if (cancelledHook) return;
          if (snap && snap.status === "running") {
            setJob(snap);
            attachStream(snap);
          } else if (!streamedIdRef.current) {
            // No active job and we aren't tailing a finishing one.
            setJob((p) => (p && p.status === "running" ? null : p));
          }
        })
        .catch(() => {});
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => {
      cancelledHook = true;
      clearInterval(t);
    };
  }, [attachStream]);

  useEffect(() => () => closeStream(), [closeStream]);

  // Refresh the unanalyzed count for whichever player is relevant (a finished
  // job's player, or the player whose page you're on) so the action button can
  // show how much is left — and so the idle pill knows whether to appear.
  useEffect(() => {
    const u = job && job.status !== "running" ? job.username : !job ? pageUsername : null;
    if (!u) {
      setRemaining(null);
      return;
    }
    let cancelledHook = false;
    const fetchStatus = () =>
      fetch(`${API_URL}/players/${encodeURIComponent(u)}/analyze/status`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (!cancelledHook && d) setRemaining(Math.max(0, d.games - d.analyzed));
        })
        .catch(() => {});
    fetchStatus();
    // Poll while idle so the count tracks any analysis happening elsewhere.
    const t = setInterval(fetchStatus, 8000);
    return () => {
      cancelledHook = true;
      clearInterval(t);
    };
  }, [job, pageUsername]);

  // ---- Idle state: no job, but the player you're viewing has work to do ----
  if (!job) {
    if (!pageUsername || remaining == null || remaining === 0) return null;
    const patternsHref = `/players/${encodeURIComponent(pageUsername)}/patterns`;
    if (pathname === patternsHref) return null; // patterns page has its own button
    return (
      <div className="fixed bottom-4 right-4 z-50 w-72 rounded-xl border border-neutral-700 bg-neutral-900/95 p-3 shadow-2xl backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-2 text-xs font-semibold text-neutral-200">
            <span className="inline-block h-2 w-2 rounded-full bg-neutral-400" />
            {remaining} game{remaining === 1 ? "" : "s"} not analyzed
          </span>
        </div>
        <div className="mt-2.5 flex items-center gap-2">
          <button
            onClick={() => startAnalysis(pageUsername)}
            disabled={busy}
            className="rounded-md bg-emerald-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {busy ? "Starting…" : `Analyze (${remaining})`}
          </button>
          <button
            onClick={() => router.push(patternsHref)}
            className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300"
          >
            Patterns →
          </button>
        </div>
      </div>
    );
  }

  // ---- Job state: running or finished ----
  const patternsHref = `/players/${encodeURIComponent(job.username)}/patterns`;
  const onPatternsPage = pathname === patternsHref;
  // Don't double up with the inline panel on the patterns page itself.
  if (onPatternsPage && job.status === "running") return null;

  const pct =
    job.total > 0 ? Math.min(100, Math.round((job.analyzed / job.total) * 100)) : 0;
  const running = job.status === "running";

  const statusText = running
    ? `Analyzing ${job.username}`
    : job.status === "done"
      ? "Analysis complete"
      : job.status === "cancelled"
        ? "Analysis stopped"
        : "Analysis error";

  const plyText =
    running && job.current_game_plies
      ? `Analyzing ply ${(job.current_ply ?? 0) + 1}/${job.current_game_plies}`
      : null;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-72 rounded-xl border border-neutral-700 bg-neutral-900/95 p-3 shadow-2xl backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-2 text-xs font-semibold text-neutral-200">
          {running ? (
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          ) : (
            <span
              className={
                "inline-block h-2 w-2 rounded-full " +
                (job.status === "done"
                  ? "bg-emerald-400"
                  : job.status === "error"
                    ? "bg-red-400"
                    : "bg-neutral-400")
              }
            />
          )}
          {statusText}
        </span>
      </div>

      {running && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
          <div
            className="h-full bg-emerald-500 transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      <div className="mt-2 flex items-center justify-between text-[11px] text-neutral-500">
        <span className="truncate">
          {running
            ? plyText ?? (job.last_label ? `${job.last_label}` : "Starting…")
            : `${job.plies_total} plies analyzed`}
        </span>
        <span className="tabular-nums">
          {job.analyzed}/{job.total}
          {job.errors > 0 ? ` · ${job.errors} err` : ""}
        </span>
      </div>

      <div className="mt-2.5 flex items-center gap-2">
        {running ? (
          <button
            onClick={stop}
            disabled={stopping}
            className="flex items-center gap-1.5 rounded-md border border-neutral-700 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:border-neutral-500 disabled:opacity-60"
          >
            {stopping && (
              <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-neutral-400 border-t-transparent" />
            )}
            {stopping ? "Stopping…" : "Stop"}
          </button>
        ) : (
          <button
            onClick={() => startAnalysis(job.username)}
            disabled={busy || remaining === 0}
            className="rounded-md bg-emerald-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {busy
              ? "Starting…"
              : remaining === 0
                ? "All analyzed"
                : (job.status === "cancelled" ? "Resume" : "Analyze more") +
                  (remaining != null ? ` (${remaining})` : "")}
          </button>
        )}
        <button
          onClick={() => router.push(patternsHref)}
          className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300"
        >
          {running ? "Manage →" : "View patterns →"}
        </button>
      </div>
    </div>
  );
}

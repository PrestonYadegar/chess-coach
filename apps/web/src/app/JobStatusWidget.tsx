"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { API_URL } from "@/lib/api";

const TIME_FORMATS = ["Bullet", "Blitz", "Rapid", "Classical", "Daily"];

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

interface PlayerSettings {
  auto_analyze: boolean;
  auto_depth: number;
  auto_workers: number;
  auto_batch: number;
  auto_time_format: string | null;
}

const DEFAULT_SETTINGS: PlayerSettings = {
  auto_analyze: true,
  auto_depth: 14,
  auto_workers: 4,
  auto_batch: 0,
  auto_time_format: null,
};

export default function JobStatusWidget() {
  const router = useRouter();
  const pathname = usePathname();
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [analyzedTotal, setAnalyzedTotal] = useState<number | null>(null);
  const [totalGames, setTotalGames] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [settings, setSettings] = useState<PlayerSettings>(DEFAULT_SETTINGS);
  const [savingSettings, setSavingSettings] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const streamedIdRef = useRef<string | null>(null);
  const autoContinuedRef = useRef<Set<string>>(new Set());

  const m = pathname?.match(/^\/players\/([^/]+)/);
  const pageUsername = m ? decodeURIComponent(m[1]) : null;

  // The username that is "active" — either the running job's player, or the page's player.
  const activeUsername = job ? job.username : pageUsername;

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
          setAnalyzedTotal((prev) => (prev !== null ? prev + 1 : prev));
          setRemaining((prev) => (prev !== null ? Math.max(0, prev - 1) : prev));
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

  // Load settings whenever the active username changes.
  useEffect(() => {
    if (!activeUsername) return;
    fetch(`${API_URL}/players/${encodeURIComponent(activeUsername)}/settings`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s) setSettings({ ...DEFAULT_SETTINGS, ...s });
      })
      .catch(() => {});
  }, [activeUsername]);

  const saveSettings = useCallback(
    async (patch: Partial<PlayerSettings>) => {
      if (!activeUsername) return;
      const next = { ...settings, ...patch };
      setSettings(next);
      setSavingSettings(true);
      try {
        await fetch(
          `${API_URL}/players/${encodeURIComponent(activeUsername)}/settings`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              auto_analyze: next.auto_analyze,
              auto_depth: next.auto_depth,
              auto_workers: next.auto_workers,
              auto_batch: next.auto_batch,
              auto_time_format: next.auto_time_format ?? "",
            }),
          }
        );
      } catch {
        // best-effort
      } finally {
        setSavingSettings(false);
      }
    },
    [activeUsername, settings]
  );

  const startAnalysis = useCallback(
    async (username: string, overrideSettings?: PlayerSettings) => {
      const u = encodeURIComponent(username);
      setBusy(true);
      try {
        const s = overrideSettings ?? settings;
        const body: Record<string, unknown> = {
          depth: s.auto_depth,
          workers: s.auto_workers,
          limit: s.auto_batch === 0 ? null : s.auto_batch,
          only_unanalyzed: true,
        };
        if (s.auto_time_format) {
          body.time_classes = [s.auto_time_format];
        }
        const res = await fetch(`${API_URL}/players/${u}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
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
    [attachStream, settings]
  );

  const stop = useCallback(async () => {
    if (!job) return;
    setStopping(true);
    try {
      await fetch(`${API_URL}/jobs/${job.id}/stop`, { method: "POST" });
    } catch {
      // stream will reflect cancellation
    }
  }, [job]);

  useEffect(() => {
    if (job && job.status !== "running") setStopping(false);
  }, [job]);

  // Auto-continue: keep running until all in-scope games are analyzed.
  useEffect(() => {
    if (
      job &&
      job.status === "done" &&
      job.analyzed > 0 &&
      remaining != null &&
      remaining > 0 &&
      !busy &&
      !autoContinuedRef.current.has(job.id)
    ) {
      autoContinuedRef.current.add(job.id);
      startAnalysis(job.username);
    }
  }, [job, remaining, busy, startAnalysis]);

  // Refs so interval callbacks can read current state without being dependencies.
  const remainingRef = useRef(remaining);
  remainingRef.current = remaining;
  const jobRef = useRef(job);
  jobRef.current = job;

  // Poll for an active job. Uses recursive setTimeout so the cadence can vary:
  // fast (5s) while something is running or games remain, slow (30s) when idle.
  useEffect(() => {
    let cancelled = false;
    let t: ReturnType<typeof setTimeout>;
    const poll = () => {
      fetch(`${API_URL}/jobs/active`)
        .then((r) => (r.ok ? r.json() : null))
        .then((snap: JobSnapshot | null) => {
          if (cancelled) return;
          if (snap && snap.status === "running") {
            setJob(snap);
            attachStream(snap);
          } else if (!streamedIdRef.current) {
            setJob((p) => (p && p.status === "running" ? null : p));
          }
        })
        .catch(() => {})
        .finally(() => {
          if (cancelled) return;
          const idle = remainingRef.current === 0 && !jobRef.current;
          t = setTimeout(poll, idle ? 30_000 : 5_000);
        });
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [attachStream]);

  useEffect(() => () => closeStream(), [closeStream]);

  // Refresh analyzed/total game counts. Skips the fetch when idle (remaining=0,
  // no job) since counts only change after a sync or new analysis. Uses refs so
  // the interval stays stable without re-running on every SSE event.
  const statusUsername = job?.username ?? pageUsername;
  useEffect(() => {
    if (!statusUsername) {
      setRemaining(null);
      return;
    }
    let cancelled = false;
    const fetchStatus = () => {
      // Nothing will have changed while idle — skip to avoid spurious requests.
      if (remainingRef.current === 0 && !jobRef.current) return;
      fetch(`${API_URL}/players/${encodeURIComponent(statusUsername)}/analyze/status`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (!cancelled && d) {
            setRemaining(Math.max(0, d.games - d.analyzed));
            setAnalyzedTotal(d.analyzed);
            setTotalGames(d.games);
          }
        })
        .catch(() => {});
    };
    fetchStatus();
    const t = setInterval(fetchStatus, 8000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [statusUsername]);

  const username = job ? job.username : pageUsername;

  // Auto-minimize to a circle when analysis finishes with nothing left to do.
  useEffect(() => {
    if (!job && remaining === 0 && (analyzedTotal ?? 0) > 0) {
      setMinimized(true);
    }
  }, [job, remaining, analyzedTotal]);

  // Expand out of minimized state whenever a new job starts.
  useEffect(() => {
    if (job?.status === "running") setMinimized(false);
  }, [job?.status]);

  // Hide when not on a player page with no active job — avoids stale state
  // from a previous player page visit bleeding through on home/settings pages.
  if (!pageUsername && !job) return null;

  // Nothing to show at all — no data yet.
  if (!job && (remaining == null) && (analyzedTotal ?? 0) === 0) return null;

  // On the (now-redirected) patterns page, still suppress double widget.
  const patternsHref = username ? `/players/${encodeURIComponent(username)}/patterns` : null;
  if (patternsHref && pathname === patternsHref && job?.status === "running") return null;

  // Minimized: floating circle that reopens the full widget on click.
  if (minimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        title={`${analyzedTotal ?? 0} games analyzed — click to view`}
        className="fixed bottom-4 right-4 z-50 flex h-9 w-9 items-center justify-center rounded-full border border-neutral-700 bg-neutral-900/95 shadow-2xl backdrop-blur transition-colors hover:border-emerald-600"
      >
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
      </button>
    );
  }

  // ---- Derived display values ----
  const running = job ? job.status === "running" : false;
  const pct =
    analyzedTotal != null && totalGames != null && totalGames > 0
      ? Math.min(100, Math.round((analyzedTotal / totalGames) * 100))
      : job && job.total > 0
      ? Math.min(100, Math.round((job.analyzed / job.total) * 100))
      : 0;

  const statusText = !job
    ? remaining === 0
      ? `All ${totalGames ?? analyzedTotal ?? ""} games analyzed`
      : `${remaining} game${remaining === 1 ? "" : "s"} not analyzed`
    : running
    ? `Analyzing ${job.username}`
    : job.status === "done"
    ? "Analysis complete"
    : job.status === "cancelled"
    ? "Analysis stopped"
    : "Analysis error";

  const plyText =
    job && running && job.current_game_plies
      ? `Analyzing ply ${(job.current_ply ?? 0) + 1}/${job.current_game_plies}`
      : null;

  // ---- Controls panel (expanded state) ----
  const ControlsPanel = () => (
    <div className="mt-3 space-y-2 border-t border-neutral-700 pt-3">
      {/* Depth */}
      <div className="flex items-center justify-between gap-2">
        <label className="text-[10px] text-neutral-400 w-16 shrink-0">Depth</label>
        <div className="flex items-center gap-1">
          {[10, 14, 18, 22].map((d) => (
            <button
              key={d}
              onClick={() => saveSettings({ auto_depth: d })}
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                settings.auto_depth === d
                  ? "bg-emerald-600 text-white"
                  : "bg-neutral-800 text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>
      {/* Workers */}
      <div className="flex items-center justify-between gap-2">
        <label className="text-[10px] text-neutral-400 w-16 shrink-0">Workers</label>
        <div className="flex items-center gap-1">
          {[1, 2, 4, 8].map((w) => (
            <button
              key={w}
              onClick={() => saveSettings({ auto_workers: w })}
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                settings.auto_workers === w
                  ? "bg-emerald-600 text-white"
                  : "bg-neutral-800 text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {w}
            </button>
          ))}
        </div>
      </div>
      {/* Batch size */}
      <div className="flex items-center justify-between gap-2">
        <label className="text-[10px] text-neutral-400 w-16 shrink-0">Batch</label>
        <div className="flex items-center gap-1">
          {[25, 50, 100, 0].map((b) => (
            <button
              key={b}
              onClick={() => saveSettings({ auto_batch: b })}
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                settings.auto_batch === b
                  ? "bg-emerald-600 text-white"
                  : "bg-neutral-800 text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {b === 0 ? "All" : b}
            </button>
          ))}
        </div>
      </div>
      {/* Time format scope */}
      <div className="flex items-center gap-2">
        <label className="text-[10px] text-neutral-400 w-16 shrink-0">Format</label>
        <div className="flex flex-wrap items-center gap-1">
          <button
            onClick={() => saveSettings({ auto_time_format: null })}
            className={`rounded px-2 py-0.5 text-[10px] font-medium ${
              !settings.auto_time_format
                ? "bg-emerald-600 text-white"
                : "bg-neutral-800 text-neutral-400 hover:text-neutral-200"
            }`}
          >
            All
          </button>
          {TIME_FORMATS.map((tf) => (
            <button
              key={tf}
              onClick={() =>
                saveSettings({
                  auto_time_format: settings.auto_time_format === tf ? null : tf,
                })
              }
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                settings.auto_time_format === tf
                  ? "bg-emerald-600 text-white"
                  : "bg-neutral-800 text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
      {/* Auto-analyze after sync */}
      <div className="flex items-center justify-between gap-2 pt-0.5">
        <label className="text-[10px] text-neutral-400">Auto-analyze after sync</label>
        <button
          onClick={() => saveSettings({ auto_analyze: !settings.auto_analyze })}
          className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${
            settings.auto_analyze ? "bg-emerald-600" : "bg-neutral-700"
          }`}
        >
          <span
            className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
              settings.auto_analyze ? "translate-x-3.5" : "translate-x-0.5"
            }`}
          />
        </button>
      </div>
      {savingSettings && (
        <p className="text-[9px] text-neutral-500 text-right">Saving…</p>
      )}
    </div>
  );

  return (
    <div className="fixed bottom-4 right-4 z-50 w-72 rounded-xl border border-neutral-700 bg-neutral-900/95 p-3 shadow-2xl backdrop-blur">
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-2 text-xs font-semibold text-neutral-200">
          {running ? (
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          ) : job ? (
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
          ) : (
            <span className="inline-block h-2 w-2 rounded-full bg-neutral-400" />
          )}
          {statusText}
          {running && (
            <span
              className="group relative flex h-3.5 w-3.5 cursor-default items-center justify-center rounded-full border border-neutral-600 text-[9px] text-neutral-500"
              aria-label="Background analysis info"
            >
              ?
              <span className="pointer-events-none absolute bottom-full left-1/2 mb-2 hidden w-52 -translate-x-1/2 rounded-lg border border-neutral-700 bg-neutral-800 px-2.5 py-2 text-[10px] leading-relaxed text-neutral-300 shadow-xl group-hover:block">
                Analysis runs on the server — safe to refresh or leave this page at any time.
              </span>
            </span>
          )}
        </span>
        {/* Settings toggle + minimize */}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] text-neutral-500 hover:text-neutral-300"
            title={expanded ? "Collapse settings" : "Settings"}
          >
            {expanded ? "▲" : "⚙"}
          </button>
          <button
            onClick={() => setMinimized(true)}
            className="text-[10px] text-neutral-500 hover:text-neutral-300"
            title="Minimize"
          >
            ─
          </button>
        </div>
      </div>

      {/* Progress bar (running only) */}
      {running && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
          <div
            className="h-full bg-emerald-500 transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {/* Status line */}
      {job && (
        <div className="mt-2 flex items-center justify-between text-[11px] text-neutral-500">
          {running ? (
            <>
              <span className="truncate">
                {plyText ?? (job.last_label ? `${job.last_label}` : "Starting…")}
              </span>
              <span className="tabular-nums">
                {analyzedTotal != null && totalGames != null
                  ? `${analyzedTotal}/${totalGames} games`
                  : `${job.analyzed}/${job.total}`}
                {job.errors > 0 ? ` · ${job.errors} err` : ""}
              </span>
            </>
          ) : (
            // Terminal state: show the player's overall analyzed-game count, not
            // this batch's ply/job fraction.
            <span className="tabular-nums">
              {analyzedTotal != null
                ? `${analyzedTotal} game${analyzedTotal === 1 ? "" : "s"} analyzed`
                : ""}
              {job.errors > 0 ? ` · ${job.errors} err` : ""}
            </span>
          )}
        </div>
      )}

      {/* Action buttons */}
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
            onClick={() => username && startAnalysis(username)}
            disabled={busy || remaining === 0 || !username}
            className="rounded-md bg-emerald-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {busy
              ? "Starting…"
              : remaining === 0
              ? "All analyzed"
              : !job
              ? `Analyze (${remaining})`
              : (job.status === "cancelled" ? "Resume" : "Analyze more") +
                (remaining != null ? ` (${remaining})` : "")}
          </button>
        )}
        {username && (
          <button
            onClick={() => router.push(`/players/${encodeURIComponent(username)}`)}
            className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300"
          >
            {running ? "Manage →" : "View Analysis →"}
          </button>
        )}
      </div>

      {/* Expanded controls */}
      {expanded && <ControlsPanel />}
    </div>
  );
}

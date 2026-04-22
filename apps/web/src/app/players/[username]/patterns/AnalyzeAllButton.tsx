"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TIME_CLASSES = ["classical", "rapid", "blitz", "bullet", "daily"] as const;
type TimeClass = (typeof TIME_CLASSES)[number];

interface Props {
  username: string;
}

interface Status {
  games: number;
  analyzed: number;
}

interface Progress {
  total: number;
  done: number;
  label: string;
  pliesTotal: number;
  errors: number;
  curPly?: number;
  curGamePlies?: number;
}

interface JobSnapshot {
  id: string;
  status: "running" | "done" | "error" | "cancelled";
  total: number;
  analyzed: number;
  plies_total: number;
  errors: number;
  last_label: string;
  error_message: string | null;
}

export default function AnalyzeAllButton({ username }: Props) {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [running, setRunning] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [batchSize, setBatchSize] = useState(25);
  const [depth, setDepth] = useState(18);
  const [workers, setWorkers] = useState(4);
  const [selectedClasses, setSelectedClasses] = useState<Set<TimeClass>>(
    new Set(["classical", "rapid", "blitz"])
  );
  const [error, setError] = useState<string | null>(null);
  const [autoAnalyze, setAutoAnalyze] = useState<boolean | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // Load the auto-analyze preference. depth/workers selectors below default to
  // the saved values so the manual batch matches what auto-runs use.
  useEffect(() => {
    fetch(`${API_URL}/players/${encodeURIComponent(username)}/settings`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (!s) return;
        setAutoAnalyze(Boolean(s.auto_analyze));
        if (typeof s.auto_depth === "number") setDepth(s.auto_depth);
        if (typeof s.auto_workers === "number") setWorkers(s.auto_workers);
      })
      .catch(() => {});
  }, [username]);

  const saveSetting = useCallback(
    (patch: Record<string, unknown>) => {
      fetch(`${API_URL}/players/${encodeURIComponent(username)}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }).catch(() => {});
    },
    [username]
  );

  function toggleAutoAnalyze() {
    setAutoAnalyze((prev) => {
      const next = !prev;
      saveSetting({ auto_analyze: next });
      return next;
    });
  }

  const refreshStatus = useCallback(() => {
    fetch(`${API_URL}/players/${encodeURIComponent(username)}/analyze/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setStatus({ games: d.games, analyzed: d.analyzed }))
      .catch(() => {});
  }, [username]);

  const closeStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const attachStream = useCallback(
    (id: string) => {
      const es = new EventSource(`${API_URL}/jobs/${id}/stream`);
      esRef.current = es;
      setJobId(id);
      setRunning(true);

      es.onmessage = (evt) => {
        let data: { type: string; [k: string]: unknown };
        try {
          data = JSON.parse(evt.data);
        } catch {
          return;
        }
        if (data.type === "snapshot") {
          setProgress({
            total: Number(data.total ?? 0),
            done: Number(data.analyzed ?? 0),
            label: String(data.last_label ?? ""),
            pliesTotal: Number(data.plies_total ?? 0),
            errors: Number(data.errors ?? 0),
          });
          if (data.status && data.status !== "running") {
            closeStream();
            setRunning(false);
            setJobId(null);
            refreshStatus();
            router.refresh();
          }
        } else if (data.type === "ply_progress") {
          setProgress((p) =>
            p
              ? {
                  ...p,
                  pliesTotal: Number(data.plies_done ?? p.pliesTotal),
                  label: String(data.label ?? p.label),
                  curPly: Number(data.ply ?? 0),
                  curGamePlies: Number(data.game_plies ?? 0),
                }
              : p
          );
        } else if (data.type === "start") {
          setProgress((p) => ({
            total: Number(data.games ?? p?.total ?? 0),
            done: p?.done ?? 0,
            label: p?.label ?? "",
            pliesTotal: p?.pliesTotal ?? 0,
            errors: p?.errors ?? 0,
          }));
        } else if (data.type === "game_done") {
          setProgress((p) =>
            p
              ? {
                  ...p,
                  total: Number(data.games_total ?? p.total),
                  done: Number(data.analyzed ?? p.done + 1),
                  label: String(data.label ?? ""),
                  pliesTotal: Number(data.plies_total ?? p.pliesTotal),
                }
              : p
          );
        } else if (data.type === "game_error") {
          setProgress((p) => (p ? { ...p, errors: p.errors + 1 } : p));
        } else if (
          data.type === "done" ||
          data.type === "cancelled"
        ) {
          closeStream();
          setRunning(false);
          setJobId(null);
          refreshStatus();
          router.refresh();
        } else if (data.type === "error") {
          closeStream();
          setRunning(false);
          setJobId(null);
          setError(String(data.message ?? "analysis failed"));
        }
      };

      es.onerror = () => {
        if (esRef.current) {
          closeStream();
          setRunning(false);
          setError("Connection to analysis stream lost");
        }
      };
    },
    [closeStream, refreshStatus, router]
  );

  useEffect(() => {
    refreshStatus();
    // Reattach to an in-flight job if one exists for this player.
    fetch(`${API_URL}/players/${encodeURIComponent(username)}/jobs/active`)
      .then((r) => (r.ok ? r.json() : null))
      .then((job: JobSnapshot | null) => {
        if (job && job.status === "running") {
          setProgress({
            total: job.total,
            done: job.analyzed,
            label: job.last_label,
            pliesTotal: job.plies_total,
            errors: job.errors,
          });
          attachStream(job.id);
        }
      })
      .catch(() => {});
  }, [username, refreshStatus, attachStream]);

  useEffect(() => () => closeStream(), [closeStream]);

  function toggleClass(c: TimeClass) {
    setSelectedClasses((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  }

  async function start() {
    setError(null);
    setProgress({ total: 0, done: 0, label: "", pliesTotal: 0, errors: 0 });
    try {
      const res = await fetch(
        `${API_URL}/players/${encodeURIComponent(username)}/analyze`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            depth,
            limit: batchSize,
            only_unanalyzed: true,
            workers,
            time_classes: Array.from(selectedClasses),
          }),
        }
      );
      if (!res.ok) {
        const msg = await res.text().catch(() => "");
        setError(`Failed to start (${res.status}): ${msg.slice(0, 200)}`);
        setProgress(null);
        return;
      }
      const job: JobSnapshot = await res.json();
      attachStream(job.id);
    } catch (e) {
      setError(`Failed to start: ${e instanceof Error ? e.message : String(e)}`);
      setProgress(null);
    }
  }

  async function stop() {
    if (jobId) {
      try {
        await fetch(`${API_URL}/jobs/${jobId}/stop`, { method: "POST" });
      } catch {
        // Even if the stop request fails, drop the local stream — the
        // server-side terminate-on-disconnect still cleans up workers.
      }
    }
    // Don't close the stream immediately — wait for the "cancelled" event so
    // the snapshot reflects final state. But if user is impatient, the stream
    // will close itself once the job thread emits cancelled.
  }

  const pct =
    progress && progress.total
      ? Math.min(100, Math.round((progress.done / progress.total) * 100))
      : 0;
  const unanalyzed = status ? status.games - status.analyzed : null;
  const canStart = selectedClasses.size > 0;

  return (
    <div className="mb-6 rounded-xl border border-neutral-800 bg-neutral-950 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-neutral-400">
            Bulk Analysis
          </h2>
          {status && (
            <p className="mt-1 text-sm text-neutral-500">
              {status.analyzed}/{status.games} games analyzed
              {unanalyzed != null && unanalyzed > 0 ? ` — ${unanalyzed} remaining` : ""}
            </p>
          )}
          {running && (
            <p className="mt-1 text-xs text-emerald-500">
              Running in background — safe to close this tab.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500">
            Batch
            <select
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
              disabled={running}
              className="ml-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={250}>250</option>
              <option value={500}>500</option>
            </select>
          </label>
          <label className="text-xs text-neutral-500">
            Depth
            <select
              value={depth}
              onChange={(e) => {
                const v = Number(e.target.value);
                setDepth(v);
                saveSetting({ auto_depth: v });
              }}
              disabled={running}
              className="ml-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              <option value={10}>10 (fast)</option>
              <option value={14}>14</option>
              <option value={18}>18</option>
              <option value={20}>20</option>
              <option value={24}>24 (slow)</option>
            </select>
          </label>
          <label className="text-xs text-neutral-500">
            Workers
            <select
              value={workers}
              onChange={(e) => {
                const v = Number(e.target.value);
                setWorkers(v);
                saveSetting({ auto_workers: v });
              }}
              disabled={running}
              className="ml-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-neutral-200"
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={4}>4</option>
              <option value={8}>8</option>
              <option value={10}>10</option>
            </select>
          </label>
          {running ? (
            <button
              onClick={stop}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm font-semibold text-neutral-200 hover:border-neutral-500"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={start}
              disabled={!canStart}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-neutral-800 disabled:text-neutral-500"
            >
              Analyze {batchSize} games
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-neutral-500">
          Time formats
        </span>
        {TIME_CLASSES.map((c) => {
          const on = selectedClasses.has(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => toggleClass(c)}
              disabled={running}
              className={
                "rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors " +
                (on
                  ? "border-emerald-600 bg-emerald-900/40 text-emerald-200"
                  : "border-neutral-700 bg-neutral-900 text-neutral-500 hover:text-neutral-300")
              }
            >
              {c}
            </button>
          );
        })}
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-neutral-400">
          <input
            type="checkbox"
            checked={autoAnalyze ?? true}
            onChange={toggleAutoAnalyze}
            className="h-3.5 w-3.5 accent-emerald-600"
          />
          Auto-analyze after sync
        </label>
      </div>

      {running && progress && (
        <div className="mt-4 space-y-2">
          <div className="h-2 w-full overflow-hidden rounded-full bg-neutral-800">
            <div
              className="h-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-xs text-neutral-500">
            <span>
              {progress.curGamePlies
                ? `${progress.label} — ply ${(progress.curPly ?? 0) + 1}/${progress.curGamePlies}`
                : progress.label
                  ? `Analyzed: ${progress.label}`
                  : "Starting Stockfish…"}
            </span>
            <span className="tabular-nums">
              {progress.done}/{progress.total} games · {progress.pliesTotal} plies
              {progress.errors > 0 ? ` · ${progress.errors} errors` : ""}
            </span>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}

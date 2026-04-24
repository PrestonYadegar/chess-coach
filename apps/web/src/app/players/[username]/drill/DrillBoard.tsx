"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import DrillChat from "./DrillChat";
import { useBoardTheme } from "@/lib/boardTheme";
import { API_URL } from "@/lib/api";
import { candidateEvalLabel } from "@/lib/eval";
import { applyUci, sideFromFen, fenAfterUcis } from "@/lib/chess";
import { formatMotif } from "@/lib/motifs";
import { useEngineEval } from "@/hooks/useEngineEval";
import ExploreBreadcrumb from "@/components/ExploreBreadcrumb";

interface DrillItem {
  type: "lichess_puzzle" | "own_game";
  puzzle_id?: string;
  game_id?: number;
  ply?: number;
  fen: string;
  solution_moves?: string[]; // UCI for lichess puzzles
  best_move?: string;
  played_move?: string;
  classification?: string;
  eval_cp?: number | null;
  eval_cp_before?: number | null;
  motif_tags?: string[];
  motif_details?: Record<string, unknown>;
  motif?: string;
  themes?: string[];
}

interface DrillResponse {
  username: string;
  motif: string | null;
  count: number;
  items: DrillItem[];
}

type Phase = "solving" | "correct" | "wrong" | "revealed";

export default function DrillBoard({
  username,
  initialMotif,
}: {
  username: string;
  initialMotif?: string;
}) {
  const [boardTheme] = useBoardTheme();
  const [queue, setQueue] = useState<DrillItem[]>([]);
  const [queueIdx, setQueueIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [chess, setChess] = useState<Chess | null>(null);
  const [fen, setFen] = useState<string>("");
  const [solutionIdx, setSolutionIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("solving");
  const [wrongMsg, setWrongMsg] = useState<string>("");
  const [revealedSan, setRevealedSan] = useState<string>("");

  const [exploreMode, setExploreMode] = useState(false);
  const [exploreLine, setExploreLine] = useState<string[]>([]);
  const [exploreSanLine, setExploreSanLine] = useState<string[]>([]);

  const [showLines, setShowLines] = useState(false);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = new URL(
        `/players/${encodeURIComponent(username)}/drill`,
        API_URL
      );
      if (initialMotif) url.searchParams.set("motif", initialMotif);
      url.searchParams.set("limit", "20");
      const res = await fetch(url.toString(), { cache: "no-store" });
      if (!res.ok) {
        setError(`Failed to load puzzles (${res.status}).`);
        return;
      }
      const data: DrillResponse = await res.json();
      setQueue(data.items);
      setQueueIdx(0);
    } catch {
      setError("Could not reach the chess-coach API. Is it running?");
    } finally {
      setLoading(false);
    }
  }, [username, initialMotif]);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  useEffect(() => {
    if (queue.length === 0 || queueIdx >= queue.length) return;
    const item = queue[queueIdx];
    const c = new Chess(item.fen);
    setChess(c);
    setFen(c.fen());
    setSolutionIdx(0);
    setPhase("solving");
    setWrongMsg("");
    setRevealedSan("");
    setExploreMode(false);
    setExploreLine([]);
    setExploreSanLine([]);
    setShowLines(false);
  }, [queue, queueIdx]);

  const currentItem = queue[queueIdx] ?? null;

  const [opponentMoveDone, setOpponentMoveDone] = useState(false);

  useEffect(() => {
    setOpponentMoveDone(false);
  }, [queueIdx, queue]);

  useEffect(() => {
    if (!chess || !currentItem || opponentMoveDone) return;
    if (currentItem.type !== "lichess_puzzle") {
      setOpponentMoveDone(true);
      return;
    }
    const sol = currentItem.solution_moves ?? [];
    if (sol.length < 2) {
      setOpponentMoveDone(true);
      return;
    }
    const timer = setTimeout(() => {
      const c = new Chess(chess.fen());
      applyUci(c, sol[0]);
      setChess(c);
      setFen(c.fen());
      setSolutionIdx(1);
      setOpponentMoveDone(true);
    }, 400);
    return () => clearTimeout(timer);
  }, [chess, currentItem, opponentMoveDone]);

  const solution: string[] = (() => {
    if (!currentItem) return [];
    if (currentItem.type === "lichess_puzzle") return currentItem.solution_moves ?? [];
    return currentItem.best_move ? [currentItem.best_move] : [];
  })();

  function onDrop(sourceSquare: string, targetSquare: string): boolean {
    if (phase !== "solving" || !chess || !opponentMoveDone) return false;
    const uciAttempt = sourceSquare + targetSquare;
    const expected = solution[solutionIdx];
    if (!expected) return false;

    const normalizedAttempt = uciAttempt.toLowerCase();
    const normalizedExpected = expected.toLowerCase().slice(0, 4);

    if (normalizedAttempt !== normalizedExpected) {
      setPhase("wrong");
      setWrongMsg(`Not the best move. The answer was ${expected}.`);
      return false;
    }

    const c = new Chess(chess.fen());
    applyUci(c, expected);
    setChess(c);
    setFen(c.fen());
    const nextIdx = solutionIdx + 1;

    if (currentItem?.type === "lichess_puzzle") {
      const sol = currentItem.solution_moves ?? [];
      if (nextIdx >= sol.length) {
        setPhase("correct");
        recordAttempt(true);
      } else {
        setTimeout(() => {
          const c2 = new Chess(c.fen());
          applyUci(c2, sol[nextIdx]);
          setChess(c2);
          setFen(c2.fen());
          setSolutionIdx(nextIdx + 1);
        }, 400);
        setSolutionIdx(nextIdx);
      }
    } else {
      setPhase("correct");
      recordAttempt(true);
    }
    return true;
  }

  function recordAttempt(solved: boolean) {
    if (!currentItem) return;
    const pid =
      currentItem.type === "lichess_puzzle"
        ? currentItem.puzzle_id
        : currentItem.game_id?.toString();
    if (!pid) return;
    fetch(`${API_URL}/puzzle_attempts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ puzzle_id: pid, username, solved }),
    }).catch(() => {});
  }

  function handleReveal() {
    setPhase("revealed");
    recordAttempt(false);
    if (!chess || solution.length === 0) return;
    const c = new Chess(chess.fen());
    const sans: string[] = [];
    for (let i = solutionIdx; i < solution.length; i++) {
      const san = applyUci(c, solution[i]);
      if (san) sans.push(san);
    }
    setFen(c.fen());
    setRevealedSan(sans.join("  "));
  }

  function handleNext() {
    if (queueIdx + 1 >= queue.length) fetchQueue();
    else setQueueIdx((i) => i + 1);
  }

  const boardOrientation =
    currentItem && opponentMoveDone ? sideFromFen(currentItem.fen) : "white";

  const themeTags = currentItem?.themes ?? currentItem?.motif_tags ?? [];
  const motifLabel = currentItem?.motif ? formatMotif(currentItem.motif) : null;
  const extraThemeTags = themeTags.filter((t) => t !== currentItem?.motif);

  const exploreFen = useMemo(() => {
    if (exploreLine.length === 0) return null;
    return fenAfterUcis(fen, exploreLine);
  }, [fen, exploreLine]);

  const displayFen = exploreMode && exploreFen ? exploreFen : fen;

  const { lines: candidates, loading: loadingCandidates } = useEngineEval(
    showLines ? displayFen : null,
    { multipv: 5, debounceMs: 400 }
  );

  function onExploreDrop(sourceSquare: string, targetSquare: string, piece: string): boolean {
    if (!exploreMode) return false;
    try {
      const c = new Chess(exploreFen ?? fen);
      const isPromotion =
        piece[1]?.toLowerCase() === "p" &&
        (targetSquare[1] === "8" || targetSquare[1] === "1");
      const result = c.move({
        from: sourceSquare,
        to: targetSquare,
        promotion: isPromotion ? "q" : undefined,
      });
      if (!result) return false;
      const uci = `${result.from}${result.to}${result.promotion ?? ""}`;
      setExploreLine((prev) => [...prev, uci]);
      setExploreSanLine((prev) => [...prev, result.san]);
      return true;
    } catch {
      return false;
    }
  }

  function toggleExploreMode() {
    setExploreMode((prev) => {
      if (prev) { setExploreLine([]); setExploreSanLine([]); }
      return !prev;
    });
  }

  function returnToPuzzle() {
    setExploreLine([]);
    setExploreSanLine([]);
  }

  if (loading) {
    return (
      <div className="flex min-h-64 items-center justify-center text-neutral-500">
        Loading puzzles…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
        {error}
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 px-6 py-12 text-center text-neutral-500">
        <p className="text-lg">No puzzles available.</p>
        <p className="mt-2 text-sm">
          Analyze some games first so patterns can be matched to puzzles.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start">

      {/* Left column: AI coach chat */}
      <div className="w-full lg:w-80 xl:w-96 flex-shrink-0 rounded-lg border border-neutral-800 flex flex-col lg:h-[600px]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-800 flex-shrink-0">
          <span className="text-sm font-semibold uppercase tracking-wider text-neutral-500">Ask the coach</span>
        </div>
        <div className="flex-1 min-h-0 p-1">
          <DrillChat
            fen={displayFen}
            candidates={candidates}
            evalCp={candidates[0]?.eval_cp ?? null}
            playedMove={currentItem?.type === "own_game" ? currentItem.played_move : undefined}
            bestMove={currentItem?.type === "own_game" ? currentItem.best_move : undefined}
            classification={currentItem?.type === "own_game" ? currentItem.classification : undefined}
            evalCpBefore={currentItem?.type === "own_game" ? (currentItem.eval_cp_before ?? null) : null}
            evalCpAfter={currentItem?.type === "own_game" ? (currentItem.eval_cp ?? null) : null}
            userColor={boardOrientation}
            motifDetails={currentItem?.type === "own_game" ? currentItem.motif_details : undefined}
            inline
          />
        </div>
      </div>

      {/* Center column: board */}
      <div className="flex flex-1 flex-col items-center gap-3">
        {/* Fixed-width wrapper keeps board + controls at 480px and centered */}
        <div className="flex flex-col gap-3 w-[480px]">
        <Chessboard
          position={displayFen}
          onPieceDrop={exploreMode ? onExploreDrop : onDrop}
          boardOrientation={boardOrientation}
          boardWidth={480}
          arePiecesDraggable={exploreMode || (phase === "solving" && opponentMoveDone)}
          customDarkSquareStyle={{ backgroundColor: boardTheme.dark }}
          customLightSquareStyle={{ backgroundColor: boardTheme.light }}
          customBoardStyle={{
            borderRadius: "8px",
            boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
          }}
        />

        {/* Explore mode toggle */}
        <button
          onClick={toggleExploreMode}
          className={`w-full rounded-lg border px-4 py-2 text-sm font-semibold transition-colors ${
            exploreMode
              ? "border-violet-500/60 bg-violet-600/20 text-violet-300 hover:bg-violet-600/30"
              : "border-neutral-700 text-neutral-300 hover:bg-neutral-800"
          }`}
        >
          {exploreMode ? "✕ Exit Explore Mode" : "⬡ Explore from here"}
        </button>

        {/* Explore breadcrumb */}
        {exploreMode && (
          <ExploreBreadcrumb
            sanLine={exploreSanLine}
            onReturn={returnToPuzzle}
            returnLabel="Back to puzzle"
          />
        )}
        </div>{/* end fixed-width 480px wrapper */}
      </div>

      {/* Right column: puzzle info, controls, lines */}
      <div className="flex w-full flex-col gap-4 lg:w-80 xl:w-96 lg:flex-shrink-0">
        {/* Counter + type & motif badges */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-neutral-600 mr-1">{queueIdx + 1} / {queue.length}</span>
          {currentItem?.type === "own_game" && (
            <span className="rounded border border-blue-700 bg-blue-950/40 px-2 py-0.5 text-xs text-blue-300">
              Your game
            </span>
          )}
          {motifLabel && (
            <span className="rounded border border-purple-700 bg-purple-950/40 px-2 py-0.5 text-xs text-purple-300">
              {motifLabel}
            </span>
          )}
          {extraThemeTags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-xs text-neutral-400"
            >
              {formatMotif(t)}
            </span>
          ))}
        </div>

        {/* Status / feedback */}
        {phase === "solving" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 text-sm text-neutral-300">
            {opponentMoveDone ? (
              <>Find the best move for {boardOrientation === "white" ? "White" : "Black"}.</>
            ) : (
              "Setting up position…"
            )}
          </div>
        )}
        {phase === "correct" && (
          <div className="rounded-lg border border-emerald-700 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-300">
            ✓ Correct!
          </div>
        )}
        {phase === "wrong" && (
          <div className="rounded-lg border border-red-700 bg-red-950/40 px-4 py-3 text-sm text-red-300">
            ✗ {wrongMsg}
          </div>
        )}
        {phase === "revealed" && (
          <div className="rounded-lg border border-yellow-700 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-300">
            {revealedSan ? (
              <>
                Solution: <span className="font-mono font-semibold text-yellow-200">{revealedSan}</span>
                <span className="mt-1 block text-xs text-yellow-400/70">Played out on the board.</span>
              </>
            ) : (
              "Solution played out on the board."
            )}
          </div>
        )}

        {/* Own-game context */}
        {currentItem?.type === "own_game" && currentItem.played_move && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-3 text-xs text-neutral-400">
            <span className="font-semibold text-neutral-300">You played:</span>{" "}
            {currentItem.played_move}
            {currentItem.classification && (
              <span className="ml-2 text-red-400">({currentItem.classification})</span>
            )}
          </div>
        )}

        {/* Show top lines + Show solution on same row */}
        <div className="flex gap-2">
          <button
            onClick={() => setShowLines((s) => !s)}
            className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors ${
              showLines
                ? "border-sky-500/60 bg-sky-600/20 text-sky-300 hover:bg-sky-600/30"
                : "border-neutral-700 text-neutral-300 hover:bg-neutral-800"
            }`}
          >
            {showLines ? "Hide top lines" : "Show top lines"}
          </button>

          {phase === "solving" && (
            <button
              onClick={handleReveal}
              className="flex-1 rounded-lg border border-neutral-700 px-3 py-2 text-sm font-semibold text-neutral-400 hover:border-neutral-500 hover:text-neutral-200 transition-colors"
            >
              Show solution
            </button>
          )}

          {(phase === "correct" || phase === "wrong" || phase === "revealed") && (
            <button
              onClick={handleNext}
              className="flex-1 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600"
            >
              Next puzzle →
            </button>
          )}
        </div>

        {/* Top engine lines */}
        {showLines && (
          <div className="rounded-lg border border-neutral-800 p-3">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
                Top lines
              </span>
              {loadingCandidates && (
                <span className="text-xs text-neutral-600 animate-pulse">loading…</span>
              )}
            </div>
            {candidates.length === 0 && !loadingCandidates ? (
              <p className="text-xs text-neutral-600">Calculating…</p>
            ) : (
              <div className="flex flex-col gap-1">
                {candidates.map((cand) => (
                  <div key={cand.rank} className="flex flex-wrap items-center gap-1 text-sm">
                    <span className="w-4 text-xs text-neutral-600">{cand.rank}.</span>
                    <span className="font-mono font-semibold text-neutral-200">{cand.move_san}</span>
                    {cand.pv_san.slice(1, 5).map((s, i) => (
                      <span key={i} className="font-mono text-xs text-neutral-500">{s}</span>
                    ))}
                    <span className="ml-auto font-mono text-xs text-neutral-400">
                      {candidateEvalLabel(cand)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

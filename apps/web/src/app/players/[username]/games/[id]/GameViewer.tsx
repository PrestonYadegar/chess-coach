"use client";

import React, { useState, useCallback, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Chessboard } from "react-chessboard";
import { useBoardTheme } from "@/lib/boardTheme";
import type { Arrow } from "react-chessboard/dist/chessboard/types";
import { Chess } from "chess.js";
import type { PlyAnalysis } from "./page";
import EvalChart from "./EvalChart";
import ReactMarkdown from "react-markdown";
import { API_URL } from "@/lib/api";
import type { MotifEvidence } from "@/lib/types";
import { evalLabel, candidateEvalLabel, evalToWhitePct } from "@/lib/eval";
import { uciToSan, uciSquares, buildPositions, buildMoveList, fenAfterUcis } from "@/lib/chess";
import { prettyMotif } from "@/lib/motifs";
import { useEngineEval } from "@/hooks/useEngineEval";
import ExploreBreadcrumb from "@/components/ExploreBreadcrumb";

interface Props {
  pgn: string;
  white: string;
  black: string;
  analysis: PlyAnalysis[];
  gameId: number;
  playerUsername: string;
  initialPly?: number | null;
}

const CLASSIFICATION: Record<
  string,
  { badge: string; label: string; cls: string; chip: string }
> = {
  blunder: {
    badge: "??",
    label: "Blunder",
    cls: "text-red-400",
    chip: "bg-red-500/15 text-red-300 border-red-500/30",
  },
  mistake: {
    badge: "?",
    label: "Mistake",
    cls: "text-orange-400",
    chip: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  },
  inaccuracy: {
    badge: "?!",
    label: "Inaccuracy",
    cls: "text-yellow-400",
    chip: "bg-yellow-500/15 text-yellow-300 border-yellow-500/30",
  },
  good: {
    badge: "",
    label: "Good move",
    cls: "text-emerald-400",
    chip: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  },
};

function ClassificationBadge({ cls }: { cls: string | null }) {
  if (!cls) return null;
  const c = CLASSIFICATION[cls];
  if (!c || !c.badge) return null;
  return (
    <span className={`ml-1 font-bold ${c.cls}`} title={c.label}>
      {c.badge}
    </span>
  );
}

// Parse motif_details JSON into a map of tag → evidence.
function parseMotifDetails(raw: string | null): Record<string, MotifEvidence> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

// Build a lookup from ply (0-indexed move) to analysis row.
function buildAnalysisMap(analysis: PlyAnalysis[]): Map<number, PlyAnalysis> {
  const m = new Map<number, PlyAnalysis>();
  for (const row of analysis) m.set(row.ply, row);
  return m;
}

interface SideStats {
  blunder: number;
  mistake: number;
  inaccuracy: number;
  acpl: number; // average centipawn loss
}

function emptyStats(): SideStats {
  return { blunder: 0, mistake: 0, inaccuracy: 0, acpl: 0 };
}

// Aggregate per-side analysis stats. ply is 0-indexed: even = White, odd = Black.
function computeStats(analysis: PlyAnalysis[]): { white: SideStats; black: SideStats } {
  const white = emptyStats();
  const black = emptyStats();
  const lossSum = { white: 0, black: 0 };
  const lossCount = { white: 0, black: 0 };

  const byPly = new Map<number, PlyAnalysis>();
  for (const r of analysis) byPly.set(r.ply, r);

  for (const row of analysis) {
    const isWhite = row.ply % 2 === 0;
    const side = isWhite ? white : black;
    if (row.classification === "blunder") side.blunder++;
    else if (row.classification === "mistake") side.mistake++;
    else if (row.classification === "inaccuracy") side.inaccuracy++;

    // Centipawn loss for this move, from the mover's POV.
    const prev = byPly.get(row.ply - 1);
    const evalBeforeWhite = row.ply === 0 ? 0 : prev?.eval_cp ?? null;
    const evalAfterWhite = row.eval_cp;
    if (evalBeforeWhite != null && evalAfterWhite != null) {
      const before = isWhite ? evalBeforeWhite : -evalBeforeWhite;
      const after = isWhite ? evalAfterWhite : -evalAfterWhite;
      const loss = Math.max(0, before - after);
      if (isWhite) {
        lossSum.white += loss;
        lossCount.white++;
      } else {
        lossSum.black += loss;
        lossCount.black++;
      }
    }
  }
  white.acpl = lossCount.white ? Math.round(lossSum.white / lossCount.white) : 0;
  black.acpl = lossCount.black ? Math.round(lossSum.black / lossCount.black) : 0;
  return { white, black };
}

const STAT_SYMBOL: Record<string, string> = {
  Blunders: "??",
  Mistakes: "?",
  Inaccuracies: "?!",
};

function StatRow({
  label,
  count,
  cls,
}: {
  label: string;
  count: number;
  cls: string;
}) {
  const symbol = STAT_SYMBOL[label];
  return (
    <div className="flex items-center justify-between">
      <span className={`text-sm ${cls}`}>
        {label}{symbol && <span className="ml-1 font-mono text-xs opacity-60">({symbol})</span>}
      </span>
      <span className="font-mono text-sm tabular-nums text-neutral-300">{count}</span>
    </div>
  );
}

export default function GameViewer({ pgn, white, black, analysis, gameId, playerUsername, initialPly }: Props) {
  const [boardTheme] = useBoardTheme();
  const router = useRouter();
  const positions = useMemo(() => buildPositions(pgn), [pgn]);
  const moves = useMemo(() => buildMoveList(pgn), [pgn]);
  const analysisMap = useMemo(() => buildAnalysisMap(analysis), [analysis]);
  const stats = useMemo(() => computeStats(analysis), [analysis]);

  // A deep-link ply (motif "Last seen") lands on the position *after* that move
  // (cursor = ply + 1) so the Move Detail panel shows the flagged move. Clamp to
  // the available positions.
  const initialCursor =
    initialPly != null ? Math.min(initialPly + 1, Math.max(positions.length - 1, 0)) : 0;
  const [cursor, setCursor] = useState(initialCursor);
  const playerIsBlack = black.toLowerCase() === playerUsername.toLowerCase();
  const [orientation, setOrientation] = useState<"white" | "black">(
    playerIsBlack ? "black" : "white"
  );
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<{ plies: number; depth: number } | null>(null);

  // Engine depth used by the per-game analyze endpoint (matches its API default).
  const ANALYZE_DEPTH = 18;

  // Game Story — on-demand, collapsible
  const [narrative, setNarrative] = useState<string | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [narrativeError, setNarrativeError] = useState(false);
  const [narrativeOpen, setNarrativeOpen] = useState(true);
  const hasAnalysis = analysis.length > 0;

  function generateNarrative() {
    setNarrativeLoading(true);
    setNarrativeError(false);
    fetch(`${API_URL}/games/${gameId}/narrative`, { method: "POST" })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => setNarrative(d.narrative))
      .catch(() => setNarrativeError(true))
      .finally(() => setNarrativeLoading(false));
  }
  const [selectedMotif, setSelectedMotif] = useState<string | null>(null);

  // Candidate move selection / line-stepping state (the candidate *lines*
  // themselves come from useEngineEval below).
  const [hoveredCandidate, setHoveredCandidate] = useState<number | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<number | null>(null);
  const [lineStep, setLineStep] = useState(0); // 0 = base position, N = N moves into the candidate PV

  // Explore mode state
  const [exploreMode, setExploreMode] = useState(false);
  const [exploreLine, setExploreLine] = useState<string[]>([]); // UCI moves from current mainline position
  const [exploreSanLine, setExploreSanLine] = useState<string[]>([]); // SAN labels for breadcrumb

  const flipBoard = () =>
    setOrientation((o) => (o === "white" ? "black" : "white"));

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalyzeResult(null);
    try {
      const res = await fetch(`${API_URL}/games/${gameId}/analyze?depth=${ANALYZE_DEPTH}`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
      }
      const data = await res.json();
      setAnalyzeResult({ plies: data.plies_analyzed ?? 0, depth: ANALYZE_DEPTH });
      router.refresh();
    } catch (e) {
      setAnalyzeError(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(false);
    }
  }

  const goTo = useCallback(
    (idx: number) => {
      setCursor(Math.max(0, Math.min(idx, positions.length - 1)));
      setSelectedMotif(null);
      setSelectedCandidate(null);
      setLineStep(0);
      // Reset explore line when navigating mainline
      setExploreLine([]);
      setExploreSanLine([]);
    },
    [positions.length]
  );

  const currentFen = positions[cursor] ?? positions[0];

  // Compute the FEN at the end of the explore line.
  const exploreFen = useMemo(() => {
    if (exploreLine.length === 0) return null;
    return fenAfterUcis(currentFen, exploreLine);
  }, [currentFen, exploreLine]);

  // Debounced eval of the explored position (multipv 3).
  const { lines: exploreCandidates, loading: loadingExploreCandidates } = useEngineEval(
    exploreFen,
    { multipv: 3, debounceMs: 500 }
  );
  const exploreEvalCp = exploreCandidates[0]?.eval_cp ?? null;

  // Reset selection/stepping when the mainline position changes.
  useEffect(() => {
    setSelectedCandidate(null);
    setLineStep(0);
  }, [currentFen, hasAnalysis]);

  // Top-3 candidates for the mainline position (only when analysis exists).
  const { lines: candidates, loading: loadingCandidates } = useEngineEval(
    hasAnalysis ? currentFen : null,
    { multipv: 3 }
  );

  // Handle a piece drop in explore mode. Returns true if the move was legal.
  function onPieceDrop(sourceSquare: string, targetSquare: string, piece: string): boolean {
    if (!exploreMode) return false;
    const baseFen = exploreFen ?? currentFen;
    try {
      const chess = new Chess(baseFen);
      // Auto-promote to queen when a pawn reaches the back rank.
      const isPromotion =
        piece[1]?.toLowerCase() === "p" &&
        (targetSquare[1] === "8" || targetSquare[1] === "1");
      const result = chess.move({
        from: sourceSquare,
        to: targetSquare,
        promotion: isPromotion ? "q" : undefined,
      });
      if (!result) return false;
      // Build the UCI string from the move result.
      const uci = `${result.from}${result.to}${result.promotion ?? ""}`;
      setExploreLine((prev) => [...prev, uci]);
      setExploreSanLine((prev) => [...prev, result.san]);
      setSelectedCandidate(null);
      setLineStep(0);
      setSelectedMotif(null);
      return true;
    } catch {
      return false;
    }
  }

  function returnToGame() {
    setExploreLine([]);
    setExploreSanLine([]);
  }

  function toggleExploreMode() {
    setExploreMode((prev) => {
      if (prev) {
        // Exiting — clear explore state
        setExploreLine([]);
        setExploreSanLine([]);
      }
      return !prev;
    });
  }

  // The eval of the CURRENT position is the eval *after* the move that produced
  // it — i.e. the row for the previous ply. Cursor 0 is the (even) start.
  const justMoved = cursor > 0 ? analysisMap.get(cursor - 1) : undefined;
  const mainlineEval = cursor === 0 ? 0 : justMoved?.eval_cp;

  // In explore mode, use the explored position's eval if available.
  const isExploring = exploreMode && exploreLine.length > 0;
  const currentEval = isExploring ? exploreEvalCp : mainlineEval;
  const whitePct = evalToWhitePct(currentEval);

  // Detail for the move that led to the current position.
  const playedSan = justMoved ? uciToSan(justMoved.fen, justMoved.played_move) : null;
  const bestSan = justMoved ? uciToSan(justMoved.fen, justMoved.best_move) : null;
  const showBest =
    justMoved &&
    justMoved.classification &&
    justMoved.classification !== "good" &&
    bestSan &&
    bestSan !== playedSan;
  const moverIsWhite = justMoved ? justMoved.ply % 2 === 0 : false;
  const motifs: string[] = (() => {
    if (!justMoved?.motif_tags) return [];
    try {
      const parsed = JSON.parse(justMoved.motif_tags);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  })();

  // Board overlays: arrows + square highlights for best move / selected motif.
  const motifDetails = useMemo(() => parseMotifDetails(justMoved?.motif_details ?? null), [justMoved]);

  // Compute the FEN to display on the board.
  const displayFen = useMemo(() => {
    // In explore mode, show the explored position.
    if (exploreMode && exploreFen) return exploreFen;
    // Candidate line stepping (mainline mode).
    const cand = selectedCandidate !== null ? candidates[selectedCandidate] : null;
    if (!cand || lineStep === 0) return currentFen;
    return fenAfterUcis(currentFen, cand.pv_uci.slice(0, lineStep)) ?? currentFen;
  }, [exploreMode, exploreFen, currentFen, selectedCandidate, candidates, lineStep]);

  // The next move in the candidate line (for the arrow overlay when stepping).
  const lineNextUci = useMemo(() => {
    const cand = selectedCandidate !== null ? candidates[selectedCandidate] : null;
    if (!cand) return null;
    return cand.pv_uci[lineStep] ?? null;
  }, [selectedCandidate, candidates, lineStep]);

  // Keep evaluating the line as you step into it: each time the displayed
  // position changes while stepping a candidate line, ask the engine to
  // (re)evaluate that exact position. Cache-backed, so repeats are instant.
  const { lines: lineProbeLines, loading: loadingLineProbe } = useEngineEval(
    !exploreMode && lineStep > 0 && hasAnalysis ? displayFen : null,
    { multipv: 1 }
  );
  const lineProbe = lineProbeLines[0] ?? null;

  // Arrow from hover or selected candidate at base position.
  const previewUci = useMemo(() => {
    if (exploreMode) return null; // no candidate preview in explore mode
    if (lineStep > 0) return lineNextUci;
    const idx = selectedCandidate ?? hoveredCandidate;
    if (idx !== null && candidates[idx]) return candidates[idx].pv_uci[0] ?? null;
    return null;
  }, [exploreMode, hoveredCandidate, selectedCandidate, candidates, lineStep, lineNextUci]);

  const customArrows = useMemo((): Arrow[] => {
    if (!hasAnalysis) return [];
    // In explore mode, show the best explore candidate if loading is done.
    if (isExploring) {
      const top = exploreCandidates[0];
      if (top && !loadingExploreCandidates) {
        const sq = uciSquares(top.move_uci);
        if (sq) return [[sq[0] as Arrow[0], sq[1] as Arrow[1], "rgba(0,200,100,0.85)"]];
      }
      return [];
    }
    if (selectedMotif && lineStep === 0) {
      const ev = motifDetails[selectedMotif];
      if (ev?.line && ev.line.length >= 1) {
        return ev.line.slice(0, 2).flatMap((uci, i): Arrow[] => {
          const sq = uciSquares(uci);
          if (!sq) return [];
          const color = i === 0 ? "rgba(255,165,0,0.85)" : "rgba(255,165,0,0.45)";
          return [[sq[0] as Arrow[0], sq[1] as Arrow[1], color]];
        });
      }
      if (ev?.by_move) {
        const sq = uciSquares(ev.by_move);
        if (sq) return [[sq[0] as Arrow[0], sq[1] as Arrow[1], "rgba(255,165,0,0.85)"]];
      }
      return [];
    }
    // Candidate preview (hover or selected).
    if (previewUci) {
      const sq = uciSquares(previewUci);
      if (sq) return [[sq[0] as Arrow[0], sq[1] as Arrow[1], "rgba(100,180,255,0.85)"]];
    }
    // Default: best move from analysis.
    if (lineStep === 0 && justMoved?.best_move) {
      const sq = uciSquares(justMoved.best_move);
      if (sq) return [[sq[0] as Arrow[0], sq[1] as Arrow[1], "rgba(0,200,100,0.85)"]];
    }
    return [];
  }, [hasAnalysis, isExploring, exploreCandidates, loadingExploreCandidates, selectedMotif, motifDetails, justMoved, previewUci, lineStep]);

  const customSquareStyles = useMemo(() => {
    if (!hasAnalysis) return {};
    if (isExploring) {
      const top = exploreCandidates[0];
      if (top && !loadingExploreCandidates) {
        const sq = uciSquares(top.move_uci);
        if (sq) return { [sq[1]]: { backgroundColor: "rgba(0,200,100,0.35)" } };
      }
      return {};
    }
    if (selectedMotif && lineStep === 0) {
      const ev = motifDetails[selectedMotif];
      const squares = ev?.squares ?? [];
      const styles: Record<string, React.CSSProperties> = {};
      for (const sq of squares) {
        styles[sq] = { backgroundColor: "rgba(255,165,0,0.45)" };
      }
      if (ev?.by_move) {
        const sq = uciSquares(ev.by_move);
        if (sq) styles[sq[1]] = { backgroundColor: "rgba(255,165,0,0.65)" };
      }
      return styles;
    }
    // Candidate preview.
    if (previewUci) {
      const sq = uciSquares(previewUci);
      if (sq) return { [sq[1]]: { backgroundColor: "rgba(100,180,255,0.3)" } };
    }
    // Default: highlight best_move target in green.
    if (lineStep === 0 && justMoved?.best_move) {
      const sq = uciSquares(justMoved.best_move);
      if (sq) return { [sq[1]]: { backgroundColor: "rgba(0,200,100,0.35)" } };
    }
    return {};
  }, [hasAnalysis, isExploring, exploreCandidates, loadingExploreCandidates, selectedMotif, motifDetails, justMoved, previewUci, lineStep]);

  const playerStats = playerIsBlack ? stats.black : stats.white;
  const oppStats = playerIsBlack ? stats.white : stats.black;
  const oppName = playerIsBlack ? white : black;

  const navBtn =
    "px-3 py-1.5 text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors";

  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start">

      {/* Left column: game story */}
      {hasAnalysis && (
        <div className="w-full lg:w-96 xl:w-[28rem] flex-shrink-0 rounded-lg border border-neutral-800">
          {/* Header — always visible */}
          <button
            onClick={() => setNarrativeOpen((o) => !o)}
            className="flex w-full items-center justify-between px-4 py-3 text-left"
          >
            <span className="text-sm font-semibold uppercase tracking-wider text-neutral-500">Game story</span>
            <span className="text-xs text-neutral-600">{narrativeOpen ? "▲" : "▼"}</span>
          </button>

          {narrativeOpen && (
            <div className="border-t border-neutral-800 px-4 pb-4 pt-3">
              {!narrative && !narrativeLoading && !narrativeError && (
                <button
                  onClick={generateNarrative}
                  className="w-full rounded-lg bg-emerald-700 py-2 text-xs font-semibold text-white hover:bg-emerald-600 transition-colors"
                >
                  Generate story
                </button>
              )}
              {narrativeLoading && (
                <div className="space-y-2 animate-pulse">
                  {[100, 92, 96, 85, 90, 80].map((w, i) => (
                    <div key={i} className="h-2.5 rounded bg-neutral-800" style={{ width: `${w}%` }} />
                  ))}
                </div>
              )}
              {narrativeError && (
                <div className="space-y-2">
                  <p className="text-xs text-red-400">Could not generate — check AI coach settings.</p>
                  <button onClick={generateNarrative} className="text-xs text-neutral-500 underline hover:text-neutral-300">
                    Retry
                  </button>
                </div>
              )}
              {narrative && (
                <div className="text-sm leading-relaxed text-neutral-400">
                  <ReactMarkdown
                    components={{
                      h3: ({ children }) => <h3 className="mb-1.5 mt-4 first:mt-0 text-xs font-semibold uppercase tracking-wider text-neutral-500">{children}</h3>,
                      p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
                      strong: ({ children }) => <strong className="font-medium text-neutral-200">{children}</strong>,
                    }}
                  >
                    {narrative}
                  </ReactMarkdown>
                  <button
                    onClick={() => {
                      fetch(`${API_URL}/games/${gameId}/narrative`, { method: "DELETE" }).catch(() => {});
                      setNarrative(null);
                      setNarrativeError(false);
                    }}
                    className="mt-3 text-xs text-neutral-600 underline hover:text-neutral-400"
                  >
                    Regenerate
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Board + eval bar — flex-1, inner wrapper sizes to content so everything below aligns */}
      <div className="flex flex-1 flex-col items-center gap-3">
        <div className="flex flex-col gap-3">
          {/* Opponent label */}
          <div className={`w-[480px] text-center text-sm text-neutral-400 ${hasAnalysis ? "self-end" : ""}`}>
            {orientation === "white" ? `${black} (Black)` : `${white} (White)`}
          </div>

          <div className="flex items-stretch gap-3">
            {/* Eval bar with label rendered inside */}
            {hasAnalysis && (
              <div
                className="relative flex w-9 flex-col overflow-hidden rounded border border-neutral-700"
                style={{ height: 480 }}
                title={`Eval: ${evalLabel(currentEval)}`}
              >
                {/* Black portion (top) */}
                <div
                  className="bg-neutral-800 transition-all duration-150"
                  style={{ height: `${100 - whitePct}%` }}
                />
                {/* White portion (bottom) */}
                <div
                  className="bg-neutral-100 transition-all duration-150"
                  style={{ height: `${whitePct}%` }}
                />
                {/* Eval label — sits on the side of whoever is ahead */}
                <span
                  className={`absolute inset-x-0 text-center text-xs font-extrabold tabular-nums ${
                    (currentEval ?? 0) >= 0
                      ? "bottom-1.5 text-neutral-900"
                      : "top-1.5 text-neutral-100"
                  }`}
                >
                  {loadingExploreCandidates && isExploring ? "…" : evalLabel(currentEval)}
                </span>
              </div>
            )}

            <Chessboard
              position={displayFen}
              boardWidth={480}
              arePiecesDraggable={exploreMode}
              onPieceDrop={onPieceDrop}
              boardOrientation={orientation}
              customDarkSquareStyle={{ backgroundColor: boardTheme.dark }}
              customLightSquareStyle={{ backgroundColor: boardTheme.light }}
              customArrows={customArrows}
              customSquareStyles={customSquareStyles}
            />
          </div>

          {/* Player label */}
          <div className={`w-[480px] text-center text-sm text-neutral-400 ${hasAnalysis ? "self-end" : ""}`}>
            {orientation === "white" ? `${white} (White)` : `${black} (Black)`}
          </div>

          {/* Navigation controls — unified segmented bar */}
          <div className={`flex w-[480px] items-center justify-center gap-2 text-sm ${hasAnalysis ? "self-end" : ""}`}>
            <div className="flex items-center divide-x divide-neutral-800 overflow-hidden rounded-lg border border-neutral-700">
              <button onClick={() => goTo(0)} disabled={cursor === 0 || exploreMode} className={navBtn} title="Start">
                «
              </button>
              <button onClick={() => goTo(cursor - 1)} disabled={cursor === 0 || exploreMode} className={navBtn} title="Previous">
                ‹
              </button>
              <span className="min-w-[96px] px-2 py-1.5 text-center text-neutral-500">
                {isExploring
                  ? `+${exploreLine.length} move${exploreLine.length !== 1 ? "s" : ""}`
                  : cursor === 0
                  ? "Start"
                  : `Move ${Math.ceil(cursor / 2)} ${cursor % 2 === 1 ? "(W)" : "(B)"}`}
              </span>
              <button
                onClick={() => goTo(cursor + 1)}
                disabled={cursor === positions.length - 1 || exploreMode}
                className={navBtn}
                title="Next"
              >
                ›
              </button>
              <button
                onClick={() => goTo(positions.length - 1)}
                disabled={cursor === positions.length - 1 || exploreMode}
                className={navBtn}
                title="End"
              >
                »
              </button>
            </div>
            <button
              onClick={flipBoard}
              className="rounded-lg border border-neutral-700 px-3 py-1.5 text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100"
              title="Flip board"
            >
              ⇅
            </button>
          </div>

          {/* Eval graph across the game — click to jump to a move */}
          {hasAnalysis && (
            <div className="pl-[48px]">
              <EvalChart
                analysis={analysis}
                cursor={cursor}
                onSeek={(ply) => goTo(ply + 1)}
              />
            </div>
          )}

          {/* Explore mode toggle */}
          <div className={`flex flex-col gap-2 ${hasAnalysis ? "pl-[48px]" : ""}`}>
            <button
              onClick={toggleExploreMode}
              className={`w-full rounded-lg border px-4 py-2 text-sm font-semibold transition-colors ${
                exploreMode
                  ? "border-violet-500/60 bg-violet-600/20 text-violet-300 hover:bg-violet-600/30"
                  : "border-neutral-700 text-neutral-300 hover:bg-neutral-800"
              }`}
              title={exploreMode ? "Exit explore mode" : "Explore alternative lines from this position"}
            >
              {exploreMode ? "✕ Exit Explore Mode" : "⬡ Explore from here"}
            </button>

            {/* Breadcrumb + return when exploring */}
            {exploreMode && (
              <ExploreBreadcrumb
                sanLine={exploreSanLine}
                onReturn={returnToGame}
                returnLabel="Return to game"
                className="w-full"
              />
            )}
          </div>

          {/* Analysis trigger */}
          <div className={`flex flex-col gap-1 ${hasAnalysis ? "pl-[48px]" : "items-center"}`}>
            <button
              onClick={runAnalysis}
              disabled={analyzing}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {analyzing
                ? "Analyzing… (this can take a minute)"
                : hasAnalysis
                ? "Re-analyze game"
                : "Analyze this game"}
            </button>
            {analyzing && (
              <p className="text-xs text-neutral-500">
                Running Stockfish at depth {ANALYZE_DEPTH} over every move — this can take a minute.
              </p>
            )}
            {!analyzing && analyzeResult && (
              <p className="text-xs text-emerald-400">
                ✓ Analysis complete — {analyzeResult.plies} move{analyzeResult.plies !== 1 ? "s" : ""} evaluated at depth {analyzeResult.depth}.
              </p>
            )}
            {!analyzing && !analyzeResult && hasAnalysis && (
              <p className="text-xs text-neutral-600">
                Engine analysis at depth {ANALYZE_DEPTH}.
              </p>
            )}
            {analyzeError && <p className="text-xs text-red-400">{analyzeError}</p>}
          </div>
        </div>
      </div>

      {/* Right column: analysis info + move list */}
      <div className="flex w-full flex-col gap-4 lg:w-96 xl:w-[28rem] lg:flex-shrink-0">
        {hasAnalysis && (
          <>
            {/* Explore mode panel — replaces move detail when exploring */}
            {isExploring ? (
              <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-400">
                    Exploring side-line
                  </h2>
                  <button
                    onClick={returnToGame}
                    className="text-xs text-neutral-500 hover:text-neutral-300 underline"
                  >
                    Return to game
                  </button>
                </div>

                <div className="mb-3 flex items-center gap-2">
                  <span className="text-sm text-neutral-400">Position eval:</span>
                  <span className="font-mono font-semibold text-neutral-200">
                    {loadingExploreCandidates ? "…" : evalLabel(exploreEvalCp)}
                  </span>
                </div>

                <div>
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
                      Candidates
                    </span>
                    {loadingExploreCandidates && (
                      <span className="text-xs text-neutral-600 animate-pulse">loading…</span>
                    )}
                  </div>
                  {exploreCandidates.length === 0 && !loadingExploreCandidates ? (
                    <p className="text-xs text-neutral-600">No candidates yet.</p>
                  ) : (
                    <div className="flex flex-col gap-1">
                      {exploreCandidates.map((cand) => (
                        <div
                          key={cand.rank}
                          className="flex items-center gap-2 rounded px-2 py-1 text-sm text-neutral-300"
                        >
                          <span className="w-4 text-xs text-neutral-600">{cand.rank}.</span>
                          <span className="font-mono font-semibold">{cand.move_san}</span>
                          {cand.pv_san.slice(1, 4).map((s, i) => (
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
              </div>
            ) : (
              <>
                {/* Game summary */}
                <div className="rounded-lg border border-neutral-800 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-500">
                    Game summary
                  </h2>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                    <div>
                      <div className="mb-1.5 text-xs font-semibold text-neutral-400">
                        {playerUsername} <span className="text-neutral-600">(you)</span>
                      </div>
                      <StatRow label="Blunders" count={playerStats.blunder} cls="text-red-400" />
                      <StatRow label="Mistakes" count={playerStats.mistake} cls="text-orange-400" />
                      <StatRow label="Inaccuracies" count={playerStats.inaccuracy} cls="text-yellow-400" />
                      <div className="mt-1.5 flex items-center justify-between border-t border-neutral-800 pt-1.5">
                        <div className="group relative cursor-help">
                          <span className="text-sm text-neutral-500 underline decoration-dotted decoration-neutral-600 underline-offset-2">
                            Avg. CP loss
                          </span>
                          <div className="pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 hidden w-56 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-xs text-neutral-300 shadow-lg group-hover:block">
                            Average centipawn loss — how much evaluation you gave up per move vs the engine's best. 100 cp = 1 pawn. Lower is better.
                          </div>
                        </div>
                        <span className="font-mono text-sm tabular-nums text-neutral-300">{playerStats.acpl}</span>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1.5 text-xs font-semibold text-neutral-400">{oppName}</div>
                      <StatRow label="Blunders" count={oppStats.blunder} cls="text-red-400" />
                      <StatRow label="Mistakes" count={oppStats.mistake} cls="text-orange-400" />
                      <StatRow label="Inaccuracies" count={oppStats.inaccuracy} cls="text-yellow-400" />
                      <div className="mt-1.5 flex items-center justify-between border-t border-neutral-800 pt-1.5">
                        <div className="group relative cursor-help">
                          <span className="text-sm text-neutral-500 underline decoration-dotted decoration-neutral-600 underline-offset-2">
                            Avg. CP loss
                          </span>
                          <div className="pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 hidden w-56 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-xs text-neutral-300 shadow-lg group-hover:block">
                            Average centipawn loss — how much evaluation you gave up per move vs the engine's best. 100 cp = 1 pawn. Lower is better.
                          </div>
                        </div>
                        <span className="font-mono text-sm tabular-nums text-neutral-300">{oppStats.acpl}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Current move detail — only shown when a move is selected */}
                {justMoved && (
                <div className="rounded-lg border border-neutral-800 p-4">
                  <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-500">
                    Move detail
                  </h2>
                  {(
                    <div className="flex flex-col gap-3">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <span className="font-mono text-lg text-neutral-100">
                          {Math.floor(justMoved.ply / 2) + 1}
                          {moverIsWhite ? "." : "…"} {playedSan}
                        </span>
                        {justMoved.classification && (
                          <span className={`text-sm font-semibold ${CLASSIFICATION[justMoved.classification]?.cls ?? ""}`}>
                            {CLASSIFICATION[justMoved.classification]?.label ?? justMoved.classification}
                          </span>
                        )}
                        <span className="ml-auto font-mono text-sm text-neutral-400">
                          Eval {evalLabel(mainlineEval)}
                        </span>
                      </div>

                      {showBest && (
                        <div className="text-sm text-neutral-400">
                          Best was{" "}
                          <span className="font-mono font-semibold text-emerald-400">{bestSan}</span>
                        </div>
                      )}

                      <div className="flex flex-wrap items-center gap-2">
                        {justMoved.phase && (
                          <span className="rounded-full border border-neutral-700 bg-neutral-800/60 px-2 py-0.5 text-xs capitalize text-neutral-400">
                            {justMoved.phase}
                          </span>
                        )}
                        {motifs
                          .filter((m) => !!(motifDetails[m]?.squares?.length || motifDetails[m]?.by_move || motifDetails[m]?.line?.length))
                          .map((m) => {
                            const isSelected = selectedMotif === m;
                            return (
                              <button
                                key={m}
                                onClick={() => setSelectedMotif(isSelected ? null : m)}
                                title="Click to highlight on board"
                                className={`rounded-full border px-2 py-0.5 text-xs capitalize transition-colors cursor-pointer ${
                                  isSelected
                                    ? "border-orange-400/60 bg-orange-500/25 text-orange-300"
                                    : "border-sky-500/30 bg-sky-500/15 text-sky-300 hover:border-sky-400/50 hover:bg-sky-500/25"
                                }`}
                              >
                                {prettyMotif(m)}
                              </button>
                            );
                          })}
                      </div>

                      {/* Motif evidence panel */}
                      {selectedMotif && motifDetails[selectedMotif] && (() => {
                        const ev = motifDetails[selectedMotif];
                        return (
                          <div className="rounded border border-orange-500/20 bg-orange-500/5 p-2 text-xs text-neutral-300">
                            <span className="font-semibold capitalize text-orange-300">{prettyMotif(selectedMotif)}</span>
                            {ev.squares && ev.squares.length > 0 && (
                              <div className="mt-1">
                                Squares:{" "}
                                {ev.squares.map((s) => (
                                  <span key={s} className="font-mono mr-1 rounded bg-neutral-800 px-1 text-orange-200">{s}</span>
                                ))}
                              </div>
                            )}
                            {ev.pieces && ev.pieces.length > 0 && (
                              <div className="mt-1">
                                Pieces:{" "}
                                {ev.pieces.map((p, i) => (
                                  <span key={i} className="mr-1 capitalize text-neutral-400">{p}</span>
                                ))}
                              </div>
                            )}
                            {(ev.by_move || ev.exploiting) && (
                              <div className="mt-1">
                                Key move:{" "}
                                <span className="font-mono rounded bg-neutral-800 px-1 text-orange-200">
                                  {ev.by_move ?? ev.exploiting}
                                </span>
                              </div>
                            )}
                            {ev.line && ev.line.length > 0 && (
                              <div className="mt-1">
                                Line:{" "}
                                {ev.line.map((m, i) => (
                                  <span key={i} className="font-mono mr-1 rounded bg-neutral-800 px-1 text-neutral-400">{m}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })()}

                      {/* Candidate moves */}
                      <div>
                        <div className="mb-1.5 flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
                            Top candidates
                          </span>
                          {loadingCandidates && (
                            <span className="text-xs text-neutral-600 animate-pulse">loading…</span>
                          )}
                        </div>
                        {candidates.length === 0 && !loadingCandidates ? (
                          <p className="text-xs text-neutral-600">No candidates available.</p>
                        ) : (
                          <div className="flex flex-col gap-1">
                            {candidates.map((cand, idx) => {
                              const isSelected = selectedCandidate === idx;
                              return (
                                <div key={cand.rank}
                                  className={`flex w-full flex-wrap items-center gap-1 rounded px-2 py-1.5 transition-colors ${
                                    isSelected ? "bg-sky-900/40" : "hover:bg-neutral-800"
                                  }`}
                                  onMouseEnter={() => setHoveredCandidate(idx)}
                                  onMouseLeave={() => setHoveredCandidate(null)}
                                >
                                  <span className="w-4 shrink-0 text-xs text-neutral-600">{cand.rank}.</span>
                                  {cand.pv_san.slice(0, 8).map((san, si) => (
                                    <button
                                      key={si}
                                      onClick={() => {
                                        if (isSelected && lineStep === si + 1) {
                                          setSelectedCandidate(null);
                                          setLineStep(0);
                                        } else {
                                          setSelectedCandidate(idx);
                                          setSelectedMotif(null);
                                          setLineStep(si + 1);
                                        }
                                      }}
                                      className={`rounded px-1.5 py-0.5 font-mono text-xs transition-colors ${
                                        isSelected && lineStep === si + 1
                                          ? "bg-sky-600 text-white"
                                          : isSelected
                                          ? "bg-neutral-800 text-sky-200 hover:bg-neutral-700"
                                          : "bg-neutral-800 text-neutral-400 hover:bg-neutral-700"
                                      }`}
                                    >
                                      {san}
                                    </button>
                                  ))}
                                  <span className="ml-auto font-mono text-xs text-neutral-400">
                                    {isSelected && lineStep > 0
                                      ? loadingLineProbe || !lineProbe ? "…" : candidateEvalLabel(lineProbe)
                                      : candidateEvalLabel(cand)}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                )}

              </>
            )}
          </>
        )}

        {/* Move list */}
        <div className="rounded-lg border border-neutral-800 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-500">
            Moves
          </h2>
          {moves.length === 0 ? (
            <p className="text-sm text-neutral-500">No moves found.</p>
          ) : (
            <div className="grid grid-cols-[auto_1fr_1fr] gap-x-2 gap-y-0.5 text-sm font-mono">
              {Array.from({ length: Math.ceil(moves.length / 2) }, (_, i) => {
                const whiteIdx = i * 2;
                const blackIdx = i * 2 + 1;
                // Classification for move at index k lives at ply=k. The board
                // cursor for that move is k+1 (the position after it is played).
                const whiteAnalysis = analysisMap.get(whiteIdx);
                const blackAnalysis = analysisMap.get(blackIdx);
                return (
                  <React.Fragment key={i}>
                    <span className="select-none text-neutral-600">
                      {i + 1}.
                    </span>
                    <button
                      key={`w${i}`}
                      onClick={() => !exploreMode && goTo(whiteIdx + 1)}
                      className={`flex items-center rounded px-1 text-left ${
                        exploreMode
                          ? "cursor-default opacity-60"
                          : cursor === whiteIdx + 1
                          ? "bg-neutral-700 text-neutral-100"
                          : "text-neutral-300 hover:bg-neutral-800"
                      }`}
                    >
                      <span>{moves[whiteIdx]}</span>
                      <ClassificationBadge cls={whiteAnalysis?.classification ?? null} />
                    </button>
                    {moves[blackIdx] != null ? (
                      <button
                        key={`b${i}`}
                        onClick={() => !exploreMode && goTo(blackIdx + 1)}
                        className={`flex items-center rounded px-1 text-left ${
                          exploreMode
                            ? "cursor-default opacity-60"
                            : cursor === blackIdx + 1
                            ? "bg-neutral-700 text-neutral-100"
                            : "text-neutral-300 hover:bg-neutral-800"
                        }`}
                      >
                        <span>{moves[blackIdx]}</span>
                        <ClassificationBadge cls={blackAnalysis?.classification ?? null} />
                      </button>
                    ) : (
                      <span />
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          )}

          {!hasAnalysis && (
            <p className="mt-4 text-xs text-neutral-600">
              No analysis yet. Click{" "}
              <span className="font-semibold text-neutral-400">Analyze this game</span> below the
              board to enable the eval bar, move classifications, and the summary above.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

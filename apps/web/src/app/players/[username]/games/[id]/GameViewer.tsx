"use client";

import { useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import type { PlyAnalysis } from "./page";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Props {
  pgn: string;
  white: string;
  black: string;
  analysis: PlyAnalysis[];
  gameId: number;
  playerUsername: string;
}

function buildPositions(pgn: string): string[] {
  const chess = new Chess();
  try {
    chess.loadPgn(pgn);
  } catch {
    return [new Chess().fen()];
  }
  const history = chess.history({ verbose: true });
  const positions: string[] = [];
  const game = new Chess();
  positions.push(game.fen());
  for (const move of history) {
    game.move(move.san);
    positions.push(game.fen());
  }
  return positions;
}

function buildMoveList(pgn: string): string[] {
  const chess = new Chess();
  try {
    chess.loadPgn(pgn);
  } catch {
    return [];
  }
  return chess.history();
}

// Convert a UCI move to SAN given the position it was played from.
function uciToSan(fen: string | null, uci: string | null): string | null {
  if (!fen || !uci) return uci;
  try {
    const c = new Chess(fen);
    const m = c.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: uci.length > 4 ? uci.slice(4, 5) : undefined,
    });
    return m.san;
  } catch {
    return uci;
  }
}

// Convert centipawn eval (white POV) to white's percentage of the bar (0–100).
// Positive eval = white winning. Clamped to ±1000 cp.
function evalToWhitePct(evalCp: number | null | undefined): number {
  if (evalCp == null) return 50;
  const clamped = Math.max(-1000, Math.min(1000, evalCp));
  return 50 + (clamped / 1000) * 45; // 5%–95% range so colors always visible
}

function evalLabel(evalCp: number | null | undefined): string {
  if (evalCp == null) return "—";
  const abs = Math.abs(evalCp);
  const sign = evalCp > 0 ? "+" : evalCp < 0 ? "−" : "";
  const pawns = (abs / 100).toFixed(1);
  return `${sign}${pawns}`;
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

function prettyMotif(tag: string): string {
  return tag.replace(/_/g, " ");
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

function StatRow({
  label,
  count,
  cls,
}: {
  label: string;
  count: number;
  cls: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className={`text-sm ${cls}`}>{label}</span>
      <span className="font-mono text-sm tabular-nums text-neutral-300">{count}</span>
    </div>
  );
}

export default function GameViewer({ pgn, white, black, analysis, gameId, playerUsername }: Props) {
  const router = useRouter();
  const positions = useMemo(() => buildPositions(pgn), [pgn]);
  const moves = useMemo(() => buildMoveList(pgn), [pgn]);
  const analysisMap = useMemo(() => buildAnalysisMap(analysis), [analysis]);
  const stats = useMemo(() => computeStats(analysis), [analysis]);

  const [cursor, setCursor] = useState(0);
  const playerIsBlack = black.toLowerCase() === playerUsername.toLowerCase();
  const [orientation, setOrientation] = useState<"white" | "black">(
    playerIsBlack ? "black" : "white"
  );
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const flipBoard = () =>
    setOrientation((o) => (o === "white" ? "black" : "white"));

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const res = await fetch(`${API_URL}/games/${gameId}/analyze`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
      }
      router.refresh();
    } catch (e) {
      setAnalyzeError(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(false);
    }
  }

  const goTo = useCallback(
    (idx: number) => setCursor(Math.max(0, Math.min(idx, positions.length - 1))),
    [positions.length]
  );

  const currentFen = positions[cursor] ?? positions[0];
  const hasAnalysis = analysis.length > 0;

  // The eval of the CURRENT position is the eval *after* the move that produced
  // it — i.e. the row for the previous ply. Cursor 0 is the (even) start.
  const justMoved = cursor > 0 ? analysisMap.get(cursor - 1) : undefined;
  const currentEval = cursor === 0 ? 0 : justMoved?.eval_cp;
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

  const playerStats = playerIsBlack ? stats.black : stats.white;
  const oppStats = playerIsBlack ? stats.white : stats.black;
  const oppName = playerIsBlack ? white : black;

  const navBtn =
    "px-3 py-1.5 text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors";

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      {/* Board + eval bar */}
      <div className="flex flex-col items-center gap-3">
        <div className="text-sm text-neutral-400">
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
                {evalLabel(currentEval)}
              </span>
            </div>
          )}

          <div className="w-full max-w-[480px]">
            <Chessboard
              position={currentFen}
              boardWidth={480}
              arePiecesDraggable={false}
              boardOrientation={orientation}
              customDarkSquareStyle={{ backgroundColor: "#4a7c59" }}
              customLightSquareStyle={{ backgroundColor: "#f0d9b5" }}
            />
          </div>
        </div>

        <div className="text-sm text-neutral-400">
          {orientation === "white" ? `${white} (White)` : `${black} (Black)`}
        </div>

        {/* Navigation controls — unified segmented bar */}
        <div className="flex items-center gap-2 text-sm">
          <div className="flex items-center divide-x divide-neutral-800 overflow-hidden rounded-lg border border-neutral-700">
            <button onClick={() => goTo(0)} disabled={cursor === 0} className={navBtn} title="Start">
              «
            </button>
            <button onClick={() => goTo(cursor - 1)} disabled={cursor === 0} className={navBtn} title="Previous">
              ‹
            </button>
            <span className="min-w-[96px] px-2 py-1.5 text-center text-neutral-500">
              {cursor === 0 ? "Start" : `Move ${Math.ceil(cursor / 2)} ${cursor % 2 === 1 ? "(W)" : "(B)"}`}
            </span>
            <button
              onClick={() => goTo(cursor + 1)}
              disabled={cursor === positions.length - 1}
              className={navBtn}
              title="Next"
            >
              ›
            </button>
            <button
              onClick={() => goTo(positions.length - 1)}
              disabled={cursor === positions.length - 1}
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

        {/* Analysis trigger */}
        <div className="flex flex-col items-center gap-1">
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
          {analyzeError && <p className="text-xs text-red-400">{analyzeError}</p>}
        </div>
      </div>

      {/* Right column: analysis info + move list */}
      <div className="flex flex-1 flex-col gap-4">
        {hasAnalysis && (
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
                    <span className="text-sm text-neutral-500">Avg. CP loss</span>
                    <span className="font-mono text-sm tabular-nums text-neutral-300">{playerStats.acpl}</span>
                  </div>
                </div>
                <div>
                  <div className="mb-1.5 text-xs font-semibold text-neutral-400">{oppName}</div>
                  <StatRow label="Blunders" count={oppStats.blunder} cls="text-red-400" />
                  <StatRow label="Mistakes" count={oppStats.mistake} cls="text-orange-400" />
                  <StatRow label="Inaccuracies" count={oppStats.inaccuracy} cls="text-yellow-400" />
                  <div className="mt-1.5 flex items-center justify-between border-t border-neutral-800 pt-1.5">
                    <span className="text-sm text-neutral-500">Avg. CP loss</span>
                    <span className="font-mono text-sm tabular-nums text-neutral-300">{oppStats.acpl}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Current move detail */}
            <div className="rounded-lg border border-neutral-800 p-4">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-neutral-500">
                Move detail
              </h2>
              {!justMoved ? (
                <p className="text-sm text-neutral-500">
                  Step through the moves to see analysis for each position.
                </p>
              ) : (
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
                      Eval {evalLabel(currentEval)}
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
                    {motifs.map((m) => (
                      <span
                        key={m}
                        className="rounded-full border border-sky-500/30 bg-sky-500/15 px-2 py-0.5 text-xs capitalize text-sky-300"
                      >
                        {prettyMotif(m)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
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
                  <>
                    <span key={`n${i}`} className="select-none text-neutral-600">
                      {i + 1}.
                    </span>
                    <button
                      key={`w${i}`}
                      onClick={() => goTo(whiteIdx + 1)}
                      className={`flex items-center rounded px-1 text-left ${
                        cursor === whiteIdx + 1
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
                        onClick={() => goTo(blackIdx + 1)}
                        className={`flex items-center rounded px-1 text-left ${
                          cursor === blackIdx + 1
                            ? "bg-neutral-700 text-neutral-100"
                            : "text-neutral-300 hover:bg-neutral-800"
                        }`}
                      >
                        <span>{moves[blackIdx]}</span>
                        <ClassificationBadge cls={blackAnalysis?.classification ?? null} />
                      </button>
                    ) : (
                      <span key={`b${i}`} />
                    )}
                  </>
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

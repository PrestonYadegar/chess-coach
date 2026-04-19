"use client";

import { useState, useCallback } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";
import type { PlyAnalysis } from "./page";

interface Props {
  pgn: string;
  white: string;
  black: string;
  analysis: PlyAnalysis[];
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

// Convert centipawn eval to white's percentage of the bar (0–100).
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

const BADGE: Record<string, { label: string; cls: string }> = {
  blunder: { label: "??", cls: "text-red-400" },
  mistake: { label: "?", cls: "text-orange-400" },
  inaccuracy: { label: "?!", cls: "text-yellow-400" },
  good: { label: "", cls: "" },
};

function ClassificationBadge({ cls }: { cls: string | null }) {
  if (!cls) return null;
  const badge = BADGE[cls];
  if (!badge || !badge.label) return null;
  return (
    <span className={`ml-1 font-bold ${badge.cls}`} title={cls}>
      {badge.label}
    </span>
  );
}

// Build a lookup from ply (1-indexed) to analysis row.
function buildAnalysisMap(analysis: PlyAnalysis[]): Map<number, PlyAnalysis> {
  const m = new Map<number, PlyAnalysis>();
  for (const row of analysis) {
    m.set(row.ply, row);
  }
  return m;
}

export default function GameViewer({ pgn, white, black, analysis }: Props) {
  const positions = buildPositions(pgn);
  const moves = buildMoveList(pgn);
  const [cursor, setCursor] = useState(0);
  const analysisMap = buildAnalysisMap(analysis);

  const goTo = useCallback(
    (idx: number) => setCursor(Math.max(0, Math.min(idx, positions.length - 1))),
    [positions.length]
  );

  const currentFen = positions[cursor] ?? positions[0];

  // ply=N in analysis = position at cursor=N (eval of that position, move played FROM it).
  const currentAnalysis = analysisMap.get(cursor);
  const currentEval = currentAnalysis?.eval_cp;
  const whitePct = evalToWhitePct(currentEval);
  const hasAnalysis = analysis.length > 0;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      {/* Board + eval bar */}
      <div className="flex flex-col items-center gap-3">
        <div className="text-sm text-neutral-400">{black} (Black)</div>

        <div className="flex items-stretch gap-3">
          {/* Eval bar */}
          {hasAnalysis && (
            <div className="flex w-5 flex-col rounded overflow-hidden border border-neutral-700" title={evalLabel(currentEval)}>
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
            </div>
          )}

          <div className="w-full max-w-[480px]">
            <Chessboard
              position={currentFen}
              boardWidth={480}
              arePiecesDraggable={false}
              customDarkSquareStyle={{ backgroundColor: "#4a7c59" }}
              customLightSquareStyle={{ backgroundColor: "#f0d9b5" }}
            />
          </div>
        </div>

        <div className="text-sm text-neutral-400">{white} (White)</div>

        {/* Eval label */}
        {hasAnalysis && (
          <div className="text-xs text-neutral-500 font-mono">
            {cursor === 0 ? "Starting position" : `Eval: ${evalLabel(currentEval)}`}
          </div>
        )}

        {/* Navigation controls */}
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => goTo(0)}
            disabled={cursor === 0}
            className="rounded border border-neutral-700 px-3 py-1.5 hover:border-neutral-500 disabled:opacity-30"
            title="Start"
          >
            ⏮
          </button>
          <button
            onClick={() => goTo(cursor - 1)}
            disabled={cursor === 0}
            className="rounded border border-neutral-700 px-3 py-1.5 hover:border-neutral-500 disabled:opacity-30"
            title="Previous"
          >
            ◀
          </button>
          <span className="min-w-[80px] text-center text-neutral-500">
            {cursor === 0 ? "Start" : `Move ${Math.ceil(cursor / 2)} ${cursor % 2 === 1 ? "(W)" : "(B)"}`}
          </span>
          <button
            onClick={() => goTo(cursor + 1)}
            disabled={cursor === positions.length - 1}
            className="rounded border border-neutral-700 px-3 py-1.5 hover:border-neutral-500 disabled:opacity-30"
            title="Next"
          >
            ▶
          </button>
          <button
            onClick={() => goTo(positions.length - 1)}
            disabled={cursor === positions.length - 1}
            className="rounded border border-neutral-700 px-3 py-1.5 hover:border-neutral-500 disabled:opacity-30"
            title="End"
          >
            ⏭
          </button>
        </div>
      </div>

      {/* Move list */}
      <div className="flex-1 rounded-lg border border-neutral-800 p-4">
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
              // classification for move at index i lives at ply=i (position moved FROM)
              const whiteAnalysis = analysisMap.get(whiteIdx);
              const blackAnalysis = analysisMap.get(blackIdx);
              const whitePly = whiteIdx + 1;
              const blackPly = blackIdx + 1;
              return (
                <>
                  <span key={`n${i}`} className="text-neutral-600 select-none">
                    {i + 1}.
                  </span>
                  <button
                    key={`w${i}`}
                    onClick={() => goTo(whitePly)}
                    className={`px-1 text-left rounded flex items-center ${
                      cursor === whitePly
                        ? "bg-neutral-700 text-neutral-100"
                        : "hover:bg-neutral-800 text-neutral-300"
                    }`}
                  >
                    <span>{moves[whiteIdx]}</span>
                    <ClassificationBadge cls={whiteAnalysis?.classification ?? null} />
                  </button>
                  {moves[blackIdx] != null ? (
                    <button
                      key={`b${i}`}
                      onClick={() => goTo(blackPly)}
                      className={`px-1 text-left rounded flex items-center ${
                        cursor === blackPly
                          ? "bg-neutral-700 text-neutral-100"
                          : "hover:bg-neutral-800 text-neutral-300"
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
            No analysis yet. Run <code className="font-mono">POST /games/{"{id}"}/analyze</code> to enable the eval bar and move classifications.
          </p>
        )}
      </div>
    </div>
  );
}

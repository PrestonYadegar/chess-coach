"use client";

import { useState, useCallback } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";

interface Props {
  pgn: string;
  white: string;
  black: string;
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

export default function GameViewer({ pgn, white, black }: Props) {
  const positions = buildPositions(pgn);
  const moves = buildMoveList(pgn);
  const [cursor, setCursor] = useState(0);

  const goTo = useCallback(
    (idx: number) => setCursor(Math.max(0, Math.min(idx, positions.length - 1))),
    [positions.length]
  );

  const currentFen = positions[cursor] ?? positions[0];

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      {/* Board */}
      <div className="flex flex-col items-center gap-3">
        <div className="text-sm text-neutral-400">{black} (Black)</div>
        <div className="w-full max-w-[480px]">
          <Chessboard
            position={currentFen}
            boardWidth={480}
            arePiecesDraggable={false}
            customDarkSquareStyle={{ backgroundColor: "#4a7c59" }}
            customLightSquareStyle={{ backgroundColor: "#f0d9b5" }}
          />
        </div>
        <div className="text-sm text-neutral-400">{white} (White)</div>

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
              const whiteCursor = whiteIdx + 1;
              const blackCursor = blackIdx + 1;
              return (
                <>
                  <span key={`n${i}`} className="text-neutral-600 select-none">
                    {i + 1}.
                  </span>
                  <button
                    key={`w${i}`}
                    onClick={() => goTo(whiteCursor)}
                    className={`px-1 text-left rounded ${
                      cursor === whiteCursor
                        ? "bg-neutral-700 text-neutral-100"
                        : "hover:bg-neutral-800 text-neutral-300"
                    }`}
                  >
                    {moves[whiteIdx]}
                  </button>
                  {moves[blackIdx] != null ? (
                    <button
                      key={`b${i}`}
                      onClick={() => goTo(blackCursor)}
                      className={`px-1 text-left rounded ${
                        cursor === blackCursor
                          ? "bg-neutral-700 text-neutral-100"
                          : "hover:bg-neutral-800 text-neutral-300"
                      }`}
                    >
                      {moves[blackIdx]}
                    </button>
                  ) : (
                    <span key={`b${i}`} />
                  )}
                </>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

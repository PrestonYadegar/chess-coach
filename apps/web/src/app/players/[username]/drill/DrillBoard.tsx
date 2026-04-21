"use client";

import { useState, useEffect, useCallback } from "react";
import { Chessboard } from "react-chessboard";
import { Chess } from "chess.js";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface DrillItem {
  type: "lichess_puzzle" | "own_game";
  puzzle_id?: string;
  game_id?: number;
  ply?: number;
  fen: string;
  solution_moves?: string[]; // UCI for lichess puzzles
  best_move?: string;        // UCI for own_game
  played_move?: string;
  classification?: string;
  motif_tags?: string[];
  motif?: string;
  themes?: string[];
}

interface DrillResponse {
  username: string;
  motif: string | null;
  count: number;
  items: DrillItem[];
}

const MOTIF_LABELS: Record<string, string> = {
  hanging_piece: "Hanging Piece",
  fork_missed: "Fork Missed",
  skewer_missed: "Skewer Missed",
  back_rank: "Back Rank",
  pin_missed: "Pin Missed",
  discovered_attack: "Discovered Attack",
  overloaded_piece: "Overloaded Piece",
  intermezzo_missed: "Intermezzo Missed",
  only_move_missed: "Only Move Missed",
  mating_net_missed: "Mating Net Missed",
  mating_net_allowed: "Mating Net Allowed",
  king_safety: "King Safety",
  pawn_structure: "Pawn Structure",
  endgame_technique: "Endgame Technique",
  opening_principle: "Opening Principle",
};

// Determine board orientation from the FEN side to move
function sideFromFen(fen: string): "white" | "black" {
  const parts = fen.split(" ");
  return parts[1] === "b" ? "black" : "white";
}

// Apply a UCI move to a Chess instance; return move SAN or null on illegal
function applyUci(chess: Chess, uci: string): string | null {
  try {
    const m = chess.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: uci.length > 4 ? uci[4] : undefined,
    });
    return m.san;
  } catch {
    return null;
  }
}

type Phase = "solving" | "correct" | "wrong" | "revealed";

export default function DrillBoard({
  username,
  initialMotif,
}: {
  username: string;
  initialMotif?: string;
}) {
  const [queue, setQueue] = useState<DrillItem[]>([]);
  const [queueIdx, setQueueIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [chess, setChess] = useState<Chess | null>(null);
  const [fen, setFen] = useState<string>("");
  const [solutionIdx, setSolutionIdx] = useState(0); // which move in solution[] we expect next
  const [phase, setPhase] = useState<Phase>("solving");
  const [streak, setStreak] = useState(0);
  const [wrongMsg, setWrongMsg] = useState<string>("");

  // Fetch a fresh queue
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

  // Load current puzzle into chess state
  useEffect(() => {
    if (queue.length === 0 || queueIdx >= queue.length) return;
    const item = queue[queueIdx];
    const c = new Chess(item.fen);
    setChess(c);
    setFen(c.fen());
    setSolutionIdx(0);
    setPhase("solving");
    setWrongMsg("");
  }, [queue, queueIdx]);

  const currentItem = queue[queueIdx] ?? null;

  // For lichess puzzles: first solution move is opponent's move; we play it automatically
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
    // Play the first (opponent) move after a short delay
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
    if (currentItem.type === "lichess_puzzle") {
      return currentItem.solution_moves ?? [];
    }
    // own_game: solution is just the best move
    return currentItem.best_move ? [currentItem.best_move] : [];
  })();

  // User drags a piece
  function onDrop(sourceSquare: string, targetSquare: string): boolean {
    if (phase !== "solving" || !chess || !opponentMoveDone) return false;

    const uciAttempt = sourceSquare + targetSquare;
    const expected = solution[solutionIdx];
    if (!expected) return false;

    // Check if the attempted UCI matches expected (ignoring promotion for simplicity)
    const normalizedAttempt = uciAttempt.toLowerCase();
    const normalizedExpected = expected.toLowerCase().slice(0, 4);

    if (normalizedAttempt !== normalizedExpected) {
      // Wrong move — snap back
      setPhase("wrong");
      setStreak(0);
      setWrongMsg(`Not the best move. The answer was ${expected}.`);
      return false;
    }

    // Correct move — apply it
    const c = new Chess(chess.fen());
    applyUci(c, expected);
    setChess(c);
    setFen(c.fen());

    const nextIdx = solutionIdx + 1;

    if (currentItem?.type === "lichess_puzzle") {
      const sol = currentItem.solution_moves ?? [];
      if (nextIdx >= sol.length) {
        // Puzzle complete
        setPhase("correct");
        setStreak((s) => s + 1);
        recordAttempt(true);
      } else {
        // Play opponent's response, then wait for user
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
      // own_game: just one move
      setPhase("correct");
      setStreak((s) => s + 1);
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
      body: JSON.stringify({
        puzzle_id: pid,
        username,
        solved,
      }),
    }).catch(() => {});
  }

  function handleReveal() {
    setPhase("revealed");
    setStreak(0);
    recordAttempt(false);
    // Show the solution on the board
    if (!chess || solution.length === 0) return;
    const c = new Chess(chess.fen());
    // replay from current solutionIdx
    for (let i = solutionIdx; i < solution.length; i++) {
      applyUci(c, solution[i]);
    }
    setFen(c.fen());
  }

  function handleNext() {
    if (queueIdx + 1 >= queue.length) {
      fetchQueue();
    } else {
      setQueueIdx((i) => i + 1);
    }
  }

  const boardOrientation =
    currentItem && opponentMoveDone ? sideFromFen(currentItem.fen) : "white";

  const themeTags = currentItem?.themes ?? currentItem?.motif_tags ?? [];
  const motifLabel = currentItem?.motif ? (MOTIF_LABELS[currentItem.motif] ?? currentItem.motif) : null;

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
    <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
      {/* Board */}
      <div className="w-full max-w-[480px] shrink-0">
        <Chessboard
          position={fen}
          onPieceDrop={onDrop}
          boardOrientation={boardOrientation}
          arePiecesDraggable={phase === "solving" && opponentMoveDone}
          customBoardStyle={{
            borderRadius: "8px",
            boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
          }}
        />
      </div>

      {/* Side panel */}
      <div className="flex flex-1 flex-col gap-4">
        {/* Streak */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-neutral-400">Streak</span>
          <span className="rounded-full bg-emerald-600/20 px-3 py-0.5 text-sm font-bold text-emerald-300">
            🔥 {streak}
          </span>
          <span className="ml-auto text-xs text-neutral-600">
            {queueIdx + 1} / {queue.length}
          </span>
        </div>

        {/* Type & motif */}
        <div className="flex flex-wrap gap-2">
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
          {themeTags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="rounded border border-neutral-700 bg-neutral-900 px-2 py-0.5 text-xs text-neutral-400"
            >
              {t}
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
            Solution shown above.
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

        {/* Action buttons */}
        <div className="flex gap-3 flex-wrap">
          {phase === "solving" && (
            <button
              onClick={handleReveal}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
            >
              Show solution
            </button>
          )}
          {(phase === "correct" || phase === "wrong" || phase === "revealed") && (
            <button
              onClick={handleNext}
              className="rounded-lg bg-emerald-700 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-600"
            >
              Next puzzle →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

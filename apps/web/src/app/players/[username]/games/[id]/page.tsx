import Link from "next/link";
import GameViewer from "./GameViewer";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Game {
  id: number;
  player_username: string;
  chesscom_id: string;
  played_at: string | null;
  time_control: string | null;
  white: string;
  black: string;
  result: string;
  eco: string | null;
  opening_name: string | null;
  opening_ply: number | null;
  pgn: string;
}

export interface PlyAnalysis {
  ply: number;
  fen: string;
  best_move: string | null;
  played_move: string | null;
  eval_cp: number | null;
  classification: string | null;
  motif_tags: string | null;
  phase: string | null;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatTimeControl(tc: string | null): string {
  if (!tc) return "—";
  const [base, inc] = tc.split("+");
  const mins = Math.floor(Number(base) / 60);
  return inc ? `${mins}+${inc}` : `${mins} min`;
}

function resultLabel(result: string, playerUsername: string, white: string): string {
  const isWhite = white.toLowerCase() === playerUsername.toLowerCase();
  if (result === "1/2-1/2") return "Draw";
  if ((result === "1-0" && isWhite) || (result === "0-1" && !isWhite)) return "Win";
  return "Loss";
}

function resultClass(label: string): string {
  if (label === "Win") return "text-emerald-400";
  if (label === "Loss") return "text-red-400";
  return "text-neutral-400";
}

export default async function GameDetailPage({
  params,
}: {
  params: { username: string; id: string };
}) {
  const username = decodeURIComponent(params.username);
  const gameId = params.id;

  let game: Game | null = null;
  let fetchError: string | null = null;
  let analysis: PlyAnalysis[] = [];

  try {
    const res = await fetch(`${API_URL}/games/${gameId}`, { cache: "no-store" });
    if (res.status === 404) {
      fetchError = "Game not found.";
    } else if (!res.ok) {
      fetchError = `Failed to load game (${res.status}).`;
    } else {
      game = await res.json();
    }
  } catch {
    fetchError = "Could not reach the chess-coach API. Is it running?";
  }

  if (game) {
    try {
      const res = await fetch(`${API_URL}/games/${gameId}/analysis`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        analysis = data.plies ?? [];
      }
    } catch {
      // analysis is optional — silently skip
    }
  }

  const label = game ? resultLabel(game.result, username, game.white) : "";
  const cls = resultClass(label);

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="mb-8">
        <Link
          href={`/players/${encodeURIComponent(username)}`}
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          ← {username}
        </Link>

        {game && (
          <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <h1 className="text-2xl font-bold tracking-tight">
              {game.white} vs {game.black}
            </h1>
            <span className={`text-lg font-semibold ${cls}`}>{label}</span>
          </div>
        )}

        {game && (
          <div className="mt-1 flex flex-wrap gap-4 text-sm text-neutral-500">
            <span>{formatDate(game.played_at)}</span>
            <span>{formatTimeControl(game.time_control)}</span>
            {game.opening_name ? (
              <span>
                {game.opening_name}
                {game.eco && <span className="text-neutral-600"> ({game.eco})</span>}
              </span>
            ) : (
              game.eco && <span>ECO: {game.eco}</span>
            )}
            <span className="font-mono text-neutral-600">{game.result}</span>
          </div>
        )}
      </div>

      {fetchError && (
        <p className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {fetchError}
        </p>
      )}

      {game && (
        <GameViewer
          pgn={game.pgn}
          white={game.white}
          black={game.black}
          analysis={analysis}
          gameId={game.id}
          playerUsername={username}
        />
      )}
    </main>
  );
}

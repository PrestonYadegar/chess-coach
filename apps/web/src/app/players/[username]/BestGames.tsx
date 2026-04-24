"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API_URL } from "@/lib/api";

interface BestGame {
  id: number;
  white: string;
  black: string;
  result: string;
  played_at: string | null;
  opening_name: string | null;
  eco: string | null;
  num_moves: number | null;
  time_control: string | null;
  acpl: number;
  blunders: number;
  mistakes: number;
  inaccuracies: number;
}

function resultLabel(game: BestGame, username: string) {
  const isWhite = game.white.toLowerCase() === username.toLowerCase();
  if (game.result === "1-0") return isWhite ? "Win" : "Loss";
  if (game.result === "0-1") return isWhite ? "Loss" : "Win";
  return "Draw";
}

function formatDate(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatTC(tc: string | null) {
  if (!tc) return null;
  const secs = parseInt(tc);
  if (isNaN(secs)) return tc;
  const mins = Math.round(secs / 60);
  return `${mins} min`;
}

function GameCard({ game, username }: { game: BestGame; username: string }) {
  const opponent = game.white.toLowerCase() === username.toLowerCase() ? game.black : game.white;
  const label = resultLabel(game, username);
  const labelColor = label === "Win" ? "text-emerald-400" : label === "Loss" ? "text-red-400" : "text-neutral-400";
  const date = formatDate(game.played_at);
  const tc = formatTC(game.time_control);

  return (
    <Link
      href={`/players/${encodeURIComponent(username)}/games/${game.id}`}
      className="group flex flex-col gap-3 rounded-xl border border-neutral-800 bg-neutral-950 p-5 transition-colors hover:border-neutral-600"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-semibold ${labelColor}`}>{label}</span>
            <span className="text-neutral-600">·</span>
            <span className="truncate text-sm text-neutral-300">vs {opponent}</span>
          </div>
          {game.opening_name && (
            <p className="mt-0.5 truncate text-xs text-neutral-500">{game.opening_name}</p>
          )}
        </div>
        <span className="flex-shrink-0 text-xs text-neutral-600 transition-colors group-hover:text-neutral-400">
          View →
        </span>
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
        {date && <span>{date}</span>}
        {tc && <><span className="text-neutral-700">·</span><span>{tc}</span></>}
        {game.num_moves && <><span className="text-neutral-700">·</span><span>{game.num_moves} moves</span></>}
      </div>

      {/* Stats chips */}
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full bg-neutral-900 px-2.5 py-1 font-medium text-emerald-400">
          {game.acpl} ACPL
        </span>
        {game.blunders === 0 && game.mistakes === 0 ? (
          <span className="rounded-full bg-neutral-900 px-2.5 py-1 text-emerald-400">Clean</span>
        ) : (
          <>
            {game.blunders > 0 && (
              <span className="rounded-full bg-neutral-900 px-2.5 py-1 text-red-400">
                {game.blunders} blunder{game.blunders !== 1 ? "s" : ""}
              </span>
            )}
            {game.mistakes > 0 && (
              <span className="rounded-full bg-neutral-900 px-2.5 py-1 text-orange-400">
                {game.mistakes} mistake{game.mistakes !== 1 ? "s" : ""}
              </span>
            )}
          </>
        )}
        {game.inaccuracies > 0 && (
          <span className="rounded-full bg-neutral-900 px-2.5 py-1 text-yellow-400">
            {game.inaccuracies} inaccurac{game.inaccuracies !== 1 ? "ies" : "y"}
          </span>
        )}
      </div>
    </Link>
  );
}

export default function BestGames({ username }: { username: string }) {
  const [games, setGames] = useState<BestGame[] | null>(null);
  const [triggered, setTriggered] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setTriggered(true); observer.disconnect(); } },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!triggered) return;
    fetch(`${API_URL}/players/${encodeURIComponent(username)}/best-games`)
      .then((r) => r.json())
      .then((d) => setGames(d.games ?? []))
      .catch(() => setGames([]));
  }, [triggered, username]);

  return (
    <div ref={ref}>
      <h2 className="mb-1 text-lg font-semibold tracking-tight">Best Games</h2>
      <p className="mb-5 text-sm text-neutral-500">
        Top performances by accuracy — lowest ACPL and fewest mistakes.
      </p>

      {!triggered || games === null ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse rounded-xl border border-neutral-800 bg-neutral-950 p-5">
              <div className="h-4 w-32 rounded bg-neutral-800" />
              <div className="mt-2 h-3 w-24 rounded bg-neutral-800" />
              <div className="mt-4 flex gap-2">
                <div className="h-6 w-16 rounded-full bg-neutral-800" />
                <div className="h-6 w-12 rounded-full bg-neutral-800" />
              </div>
            </div>
          ))}
        </div>
      ) : games.length === 0 ? (
        <p className="text-sm text-neutral-600">
          No analyzed games yet — analyze some games first to see your best performances.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {games.map((g) => (
            <GameCard key={g.id} game={g} username={username} />
          ))}
        </div>
      )}
    </div>
  );
}

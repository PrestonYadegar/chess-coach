import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PAGE_SIZE = 20;

interface Game {
  id: number;
  chesscom_id: string;
  played_at: string | null;
  time_control: string | null;
  white: string;
  black: string;
  result: string;
  eco: string | null;
}

interface GamesResponse {
  total: number;
  limit: number;
  offset: number;
  games: Game[];
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatTimeControl(tc: string | null): string {
  if (!tc) return "—";
  // "600" → "10 min", "600+5" → "10+5"
  const [base, inc] = tc.split("+");
  const mins = Math.floor(Number(base) / 60);
  return inc ? `${mins}+${inc}` : `${mins} min`;
}

function playerResult(game: Game, username: string): { label: string; className: string } {
  const lc = username.toLowerCase();
  const isWhite = game.white.toLowerCase() === lc;
  const r = game.result;
  if (r === "1/2-1/2") return { label: "Draw", className: "text-neutral-400" };
  if ((r === "1-0" && isWhite) || (r === "0-1" && !isWhite))
    return { label: "Win", className: "text-emerald-400" };
  return { label: "Loss", className: "text-red-400" };
}

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: { username: string };
  searchParams: { page?: string; result?: string; time_control?: string };
}) {
  const username = decodeURIComponent(params.username);
  const page = Math.max(1, Number(searchParams.page ?? 1));
  const offset = (page - 1) * PAGE_SIZE;
  const filterResult = searchParams.result ?? "";
  const filterTC = searchParams.time_control ?? "";

  const qs = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    ...(filterResult ? { result: filterResult } : {}),
    ...(filterTC ? { time_control: filterTC } : {}),
  });

  let data: GamesResponse | null = null;
  let fetchError: string | null = null;

  try {
    const res = await fetch(
      `${API_URL}/players/${encodeURIComponent(username)}/games?${qs}`,
      { cache: "no-store" }
    );
    if (res.status === 404) {
      fetchError = `Player "${username}" not found. Try syncing from the homepage first.`;
    } else if (!res.ok) {
      fetchError = `Failed to load games (${res.status}).`;
    } else {
      data = await res.json();
    }
  } catch {
    fetchError = "Could not reach the chess-coach API. Is it running?";
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  function pageHref(p: number) {
    const q = new URLSearchParams({
      page: String(p),
      ...(filterResult ? { result: filterResult } : {}),
      ...(filterTC ? { time_control: filterTC } : {}),
    });
    return `?${q}`;
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-300">
            ← Home
          </Link>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">{username}</h1>
          {data && (
            <p className="mt-1 text-sm text-neutral-400">{data.total} games</p>
          )}
        </div>

        <div className="flex items-center gap-3">
          <Link
            href={`/players/${encodeURIComponent(username)}/patterns`}
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
          >
            Patterns
          </Link>
          {/* Re-sync button */}
          <Link
            href={`/?resync=${encodeURIComponent(username)}`}
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
          >
            Re-sync
          </Link>
        </div>
      </div>

      {fetchError && (
        <p className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {fetchError}
        </p>
      )}

      {data && (
        <>
          <div className="overflow-hidden rounded-lg border border-neutral-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wider text-neutral-500">
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Opponent</th>
                  <th className="px-4 py-3">Result</th>
                  <th className="px-4 py-3">Time Control</th>
                  <th className="px-4 py-3">ECO</th>
                </tr>
              </thead>
              <tbody>
                {data.games.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-neutral-500">
                      No games found.
                    </td>
                  </tr>
                )}
                {data.games.map((game) => {
                  const lc = username.toLowerCase();
                  const isWhite = game.white.toLowerCase() === lc;
                  const opponent = isWhite ? game.black : game.white;
                  const { label, className } = playerResult(game, username);
                  return (
                    <tr
                      key={game.id}
                      className="border-b border-neutral-800 last:border-0 hover:bg-neutral-900"
                    >
                      <td className="px-4 py-3 text-neutral-400">
                        {formatDate(game.played_at)}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/players/${encodeURIComponent(username)}/games/${game.id}`}
                          className="font-medium hover:text-neutral-300"
                        >
                          {opponent || "—"}
                        </Link>
                      </td>
                      <td className={`px-4 py-3 font-semibold ${className}`}>{label}</td>
                      <td className="px-4 py-3 text-neutral-400">
                        {formatTimeControl(game.time_control)}
                      </td>
                      <td className="px-4 py-3 text-neutral-500">{game.eco ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-6 flex items-center justify-between text-sm">
              <span className="text-neutral-500">
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                {page > 1 && (
                  <Link
                    href={pageHref(page - 1)}
                    className="rounded-lg border border-neutral-700 px-4 py-2 hover:border-neutral-500"
                  >
                    ← Prev
                  </Link>
                )}
                {page < totalPages && (
                  <Link
                    href={pageHref(page + 1)}
                    className="rounded-lg border border-neutral-700 px-4 py-2 hover:border-neutral-500"
                  >
                    Next →
                  </Link>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}

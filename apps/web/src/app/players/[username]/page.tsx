import Link from "next/link";
import EvalSparkline from "./EvalSparkline";
import ResyncButton from "./ResyncButton";
import MotifIcon from "./MotifIcon";
import FilterBar from "./FilterBar";
import TimeFormatIcon from "./TimeFormatIcon";
import BestGames from "./BestGames";
import { API_URL } from "@/lib/api";
import { MOTIF_LABELS } from "@/lib/motifs";

const PAGE_SIZE = 20;

interface GameSummary {
  analyzed: boolean;
  acpl: number;
  blunders: number;
  mistakes: number;
  inaccuracies: number;
  eval_series: (number | null)[];
}

interface Game {
  id: number;
  chesscom_id: string;
  played_at: string | null;
  time_control: string | null;
  white: string;
  black: string;
  result: string;
  eco: string | null;
  opening_name: string | null;
  num_moves: number | null;
  summary?: GameSummary | null;
}

interface GamesResponse {
  total: number;
  limit: number;
  offset: number;
  games: Game[];
}

interface Pattern {
  motif: string;
  count: number;
  last_seen_game_id: number | null;
  last_seen_ply: number | null;
  example_fens: string[];
}

interface OpeningOption {
  name: string;
  games: number;
  moves: string | null;
}

interface AvailableFilters {
  openings: OpeningOption[];
  time_formats: string[];
  colors: string[];
}

interface PatternsResponse {
  username: string;
  patterns: Pattern[];
  phase_counts: Record<string, number>;
  available_filters?: AvailableFilters;
}

interface WinRecord {
  wins: number;
  losses: number;
  draws: number;
  total: number;
  win_pct: number;
}

interface BestOpening {
  opening_name: string;
  eco: string | null;
  moves: string | null;
  games: number;
  wins: number;
  losses: number;
  draws: number;
  win_pct: number;
}

interface StatsResponse {
  username: string;
  overall: WinRecord;
  by_color: { white: WinRecord; black: WinRecord };
  by_time_format: Record<string, WinRecord>;
  best_openings: { white: BestOpening[]; black: BestOpening[] };
}

const MOTIF_DESC: Record<string, string> = {
  hanging_piece: "Left a piece undefended or missed capturing a free piece.",
  fork_missed: "Missed a fork opportunity that wins material.",
  skewer_missed: "Missed a long-range skewer through two enemy pieces.",
  back_rank: "Vulnerable or missed a back-rank mating threat.",
  pin_missed: "Missed pinning an opponent's piece to win material.",
  discovered_attack: "Missed or fell victim to a discovered attack.",
  overloaded_piece: "A piece was overloaded and couldn't defend everything.",
  intermezzo_missed: "Played an obvious recapture instead of a forcing in-between move.",
  only_move_missed: "Had a single best move (≥ 2 pawns better than alternatives); played something else.",
  mating_net_missed: "Had a forced mate; played a move that gave it up.",
  mating_net_allowed: "Walked into a forced mate against you.",
  king_safety: "King was exposed or pawn shelter was weakened.",
  pawn_structure: "Created doubled or isolated pawns without compensation.",
  endgame_technique: "Pure pawn endgame mistake — technique failure.",
  opening_principle: "Violated an opening principle (development, center control, early queen).",
};

const PHASE_LABELS: Record<string, string> = {
  opening: "Opening",
  middlegame: "Middlegame",
  endgame: "Endgame",
};

function motifColor(index: number): string {
  const colors = [
    "border-red-700 bg-red-950/40",
    "border-orange-700 bg-orange-950/40",
    "border-yellow-700 bg-yellow-950/40",
    "border-blue-700 bg-blue-950/40",
    "border-purple-700 bg-purple-950/40",
    "border-teal-700 bg-teal-950/40",
    "border-pink-700 bg-pink-950/40",
    "border-indigo-700 bg-indigo-950/40",
    "border-emerald-700 bg-emerald-950/40",
  ];
  return colors[index % colors.length];
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

function ColorBadge({ color }: { color: "white" | "black" }) {
  // A solid two-tone disc (Go-stone style) reads instantly as "the white side /
  // the black side" at any size — a detailed king glyph turns to mush at 20px.
  return (
    <span
      className={`inline-block h-4 w-4 shrink-0 rounded-full ring-1 ${
        color === "white"
          ? "bg-neutral-50 ring-neutral-400"
          : "bg-neutral-950 ring-neutral-500"
      }`}
      aria-hidden="true"
    />
  );
}

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: { username: string };
  searchParams: {
    page?: string;
    result?: string;
    time_control?: string;
    opening?: string;
    color?: string;
    time_format?: string;
  };
}) {
  const username = decodeURIComponent(params.username);
  const page = Math.max(1, Number(searchParams.page ?? 1));
  const offset = (page - 1) * PAGE_SIZE;
  const filterResult = searchParams.result ?? "";
  const filterTC = searchParams.time_control ?? "";
  const filterOpening = searchParams.opening ?? "";
  const filterColor = searchParams.color ?? "";
  const filterTimeFormat = searchParams.time_format ?? "";

  const qs = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    ...(filterResult ? { result: filterResult } : {}),
    ...(filterTC ? { time_control: filterTC } : {}),
    ...(filterOpening ? { opening: filterOpening } : {}),
    ...(filterColor ? { color: filterColor } : {}),
    ...(filterTimeFormat ? { time_format: filterTimeFormat } : {}),
  });

  const analyticsQs = new URLSearchParams({
    ...(filterOpening ? { opening: filterOpening } : {}),
    ...(filterColor ? { color: filterColor } : {}),
    ...(filterTimeFormat ? { time_format: filterTimeFormat } : {}),
  });

  let data: GamesResponse | null = null;
  let patterns: PatternsResponse | null = null;
  let stats: StatsResponse | null = null;
  let fetchError: string | null = null;

  const playerUrl = (path: string) =>
    `${API_URL}/players/${encodeURIComponent(username)}${path}`;

  try {
    const analyticsQsStr = analyticsQs.toString();
    const [gamesRes, patternsRes, statsRes] = await Promise.all([
      fetch(playerUrl(`/games?${qs}`), { cache: "no-store" }),
      fetch(playerUrl(`/patterns${analyticsQsStr ? `?${analyticsQsStr}` : ""}`), { cache: "no-store" }),
      fetch(playerUrl(`/stats${analyticsQsStr ? `?${analyticsQsStr}` : ""}`), { cache: "no-store" }),
    ]);
    if (gamesRes.status === 404) {
      fetchError = `Player "${username}" not found. Try syncing from the homepage first.`;
    } else if (!gamesRes.ok) {
      fetchError = `Failed to load games (${gamesRes.status}).`;
    } else {
      data = await gamesRes.json();
    }
    if (patternsRes.ok) {
      patterns = await patternsRes.json();
    }
    if (statsRes.ok) {
      stats = await statsRes.json();
    }
  } catch {
    fetchError = "Could not reach the chess-coach API. Is it running?";
  }

  const allPatterns = patterns?.patterns ?? [];
  const maxCount = allPatterns.length > 0 ? allPatterns[0].count : 1;
  const phaseCounts = patterns?.phase_counts ?? {};
  const phaseTotal = Object.values(phaseCounts).reduce((a, b) => a + b, 0);
  const phaseOrder = ["opening", "middlegame", "endgame"] as const;

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  function pageHref(p: number) {
    const q = new URLSearchParams({
      page: String(p),
      ...(filterResult ? { result: filterResult } : {}),
      ...(filterTC ? { time_control: filterTC } : {}),
      ...(filterOpening ? { opening: filterOpening } : {}),
      ...(filterColor ? { color: filterColor } : {}),
      ...(filterTimeFormat ? { time_format: filterTimeFormat } : {}),
    });
    return `?${q}`;
  }

  const availableFilters = patterns?.available_filters ?? {
    openings: [],
    time_formats: [],
    colors: [],
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      {/* Header */}
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
        <ResyncButton username={username} />
      </div>

      {fetchError && (
        <p className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {fetchError}
        </p>
      )}

      {/* Filter bar */}
      {(availableFilters.openings.length > 0 ||
        availableFilters.time_formats.length > 0) && (
        <FilterBar
          available={availableFilters}
          activeOpening={filterOpening}
          activeTimeFormat={filterTimeFormat}
          activeColor={filterColor}
        />
      )}

      {/* Win/Loss/Tie insight section */}
      {stats && (
        <div className="mb-6 rounded-xl border border-neutral-800 bg-neutral-950 p-5">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Win / Loss / Draw
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {/* Overall */}
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <p className="mb-2 text-xs text-neutral-500 uppercase tracking-wider">Overall Win Rate</p>
              <p className="text-2xl font-bold text-white tabular-nums">
                {stats.overall.win_pct.toFixed(1)}%
              </p>
              <p className="mt-1 text-xs text-neutral-400 tabular-nums">
                <span className="text-emerald-400">{stats.overall.wins}W</span>{" "}
                <span className="text-red-400">{stats.overall.losses}L</span>{" "}
                <span className="text-neutral-400">{stats.overall.draws}D</span>
                {" "}· {stats.overall.total} games
              </p>
            </div>

            {/* By Color */}
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <p className="mb-2 text-xs text-neutral-500 uppercase tracking-wider">By Color</p>
              <div className="space-y-2">
                {(["white", "black"] as const).map((color) => {
                  const r = stats!.by_color[color];
                  return (
                    <div key={color} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2">
                        <ColorBadge color={color} />
                        <span className="capitalize text-neutral-300">{color}</span>
                      </span>
                      <span className="tabular-nums">
                        <span className="text-white font-medium">{r.win_pct.toFixed(1)}%</span>
                        <span className="ml-1 text-neutral-500">
                          ({r.wins}W/{r.losses}L/{r.draws}D)
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* By Time Format */}
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <p className="mb-2 text-xs text-neutral-500 uppercase tracking-wider">By Format</p>
              <div className="space-y-2">
                {Object.entries(stats.by_time_format).map(([fmt, r]) => (
                  <div key={fmt} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-neutral-300">
                      <TimeFormatIcon format={fmt} />
                      {fmt}
                    </span>
                    <span className="tabular-nums">
                      <span className="text-white font-medium">{r.win_pct.toFixed(1)}%</span>
                      <span className="ml-1 text-neutral-500">
                        ({r.wins}W/{r.losses}L/{r.draws}D)
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Best Openings */}
          {(stats.best_openings.white.length > 0 || stats.best_openings.black.length > 0) && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {(["white", "black"] as const)
                .map((color) => {
                  const openings = stats!.best_openings[color];
                  if (openings.length === 0) return null;
                  return (
                    <div key={color} className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
                      <p className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
                        <ColorBadge color={color} />
                        Best Openings as {color === "white" ? "White" : "Black"}
                      </p>
                      <div className="space-y-2">
                        {openings.map((o) => (
                          <div
                            key={o.eco ?? o.opening_name}
                            className="group relative flex items-center justify-between gap-2 text-xs"
                          >
                            <span className="truncate text-neutral-300">
                              {o.opening_name}
                            </span>
                            <span className="shrink-0 tabular-nums">
                              <span className="font-medium text-emerald-400">
                                {o.win_pct.toFixed(0)}%
                              </span>
                              <span className="ml-1 text-neutral-500">({o.games})</span>
                            </span>
                            {/* Hover snippet: ECO + representative line */}
                            <div className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 hidden w-max max-w-xs rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-[11px] leading-snug shadow-lg group-hover:block">
                              <span className="font-semibold text-neutral-200">{o.opening_name}</span>
                              {o.eco && <span className="ml-1 text-neutral-500">{o.eco}</span>}
                              {o.moves && (
                                <span className="mt-1 block font-mono text-neutral-400">{o.moves}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}

      {/* Mistakes by phase */}
      {phaseTotal > 0 && (
        <div className="mb-6 rounded-xl border border-neutral-800 bg-neutral-950 p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Mistakes by phase
          </h2>
          <div className="space-y-2">
            {phaseOrder.map((p) => {
              const n = phaseCounts[p] ?? 0;
              const pct = phaseTotal > 0 ? Math.round((n / phaseTotal) * 100) : 0;
              return (
                <div key={p} className="flex items-center gap-3 text-xs">
                  <span className="w-24 text-neutral-300">{PHASE_LABELS[p]}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-neutral-800">
                    <div
                      className="h-full bg-emerald-600"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-20 text-right tabular-nums text-neutral-500">
                    {n} ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Motif cards */}
      {allPatterns.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Top patterns
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {allPatterns.map((p, i) => {
              const label = MOTIF_LABELS[p.motif] ?? p.motif;
              const desc = MOTIF_DESC[p.motif] ?? "";
              const barPct = Math.round((p.count / maxCount) * 100);
              return (
                <div
                  key={p.motif}
                  className={`flex flex-col rounded-xl border p-5 ${motifColor(i)}`}
                >
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <MotifIcon motif={p.motif} className="shrink-0 rounded" />
                      <h3 className="text-base font-semibold leading-tight">{label}</h3>
                    </div>
                    <span className="shrink-0 rounded-full bg-neutral-800 px-2.5 py-0.5 text-xs font-bold text-neutral-200">
                      {p.count} {p.count === 1 ? "game" : "games"}
                    </span>
                  </div>
                  {desc && (
                    <p className="mb-4 text-xs text-neutral-400 leading-relaxed">{desc}</p>
                  )}
                  <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                    <div
                      className="h-full rounded-full bg-neutral-300"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <div className="mt-auto flex items-center justify-between gap-2">
                    {p.last_seen_game_id && (
                      <Link
                        href={`/players/${encodeURIComponent(username)}/games/${p.last_seen_game_id}${
                          p.last_seen_ply != null ? `?ply=${p.last_seen_ply}` : ""
                        }`}
                        className="text-xs text-neutral-500 hover:text-neutral-300"
                      >
                        Last seen →
                      </Link>
                    )}
                    <Link
                      href={`/players/${encodeURIComponent(username)}/drill?motif=${encodeURIComponent(p.motif)}`}
                      className="ml-auto rounded-lg bg-neutral-700 px-3 py-1.5 text-xs font-medium hover:bg-neutral-600"
                    >
                      Drill this
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No analysis placeholder */}
      {!fetchError && data && data.total > 0 && allPatterns.length === 0 && (
        <div className="mb-8 rounded-lg border border-neutral-800 px-6 py-12 text-center text-neutral-500">
          <p className="text-lg">No analysis yet.</p>
          <p className="mt-2 text-sm">
            Use the analysis widget to run Stockfish and surface your mistake patterns.
          </p>
        </div>
      )}

      {/* Best Games */}
      {allPatterns.length > 0 && (
        <div className="mb-10">
          <BestGames username={username} />
        </div>
      )}

      {/* Games table */}
      {data && (
        <>
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Games
          </h2>
          <div className="overflow-hidden rounded-lg border border-neutral-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-900 text-left text-xs uppercase tracking-wider text-neutral-500">
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Opponent</th>
                  <th className="px-4 py-3">Result</th>
                  <th
                    className="px-4 py-3"
                    title="Average Centipawn Loss — the average difference in evaluation between the player's move and the engine's best move. Lower is stronger."
                  >
                    Eval
                  </th>
                  <th className="px-4 py-3">Moves</th>
                  <th className="px-4 py-3">Time Control</th>
                  <th className="px-4 py-3">Opening</th>
                </tr>
              </thead>
              <tbody>
                {data.games.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-neutral-500">
                      No games found.
                    </td>
                  </tr>
                )}
                {data.games.map((game) => {
                  const lc = username.toLowerCase();
                  const isWhite = game.white.toLowerCase() === lc;
                  const opponent = isWhite ? game.black : game.white;
                  const { label, className } = playerResult(game, username);
                  const summary = game.summary;
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
                      <td className="px-4 py-3">
                        {summary?.analyzed ? (
                          <div className="flex items-center gap-3">
                            <EvalSparkline
                              series={summary.eval_series}
                              playerIsWhite={isWhite}
                            />
                            <div className="text-xs leading-tight text-neutral-500">
                              <div className="tabular-nums text-neutral-300">
                                {summary.acpl} <span className="text-neutral-600">acpl</span>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <span className="text-xs text-neutral-600">Not analyzed</span>
                        )}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-neutral-400">
                        {game.num_moves ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-neutral-400">
                        {formatTimeControl(game.time_control)}
                      </td>
                      <td className="px-4 py-3 text-neutral-400">
                        {game.opening_name ? (
                          <span title={game.eco ?? undefined}>{game.opening_name}</span>
                        ) : (
                          <span className="text-neutral-500">{game.eco ?? "—"}</span>
                        )}
                      </td>
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

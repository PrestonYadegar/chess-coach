import Link from "next/link";
import AnalyzeAllButton from "./AnalyzeAllButton";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Pattern {
  motif: string;
  count: number;
  last_seen_game_id: number | null;
  example_fens: string[];
}

interface PatternsResponse {
  username: string;
  patterns: Pattern[];
  phase_counts: Record<string, number>;
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

export default async function PatternsPage({
  params,
}: {
  params: { username: string };
}) {
  const username = decodeURIComponent(params.username);

  let data: PatternsResponse | null = null;
  let fetchError: string | null = null;

  try {
    const res = await fetch(
      `${API_URL}/players/${encodeURIComponent(username)}/patterns`,
      { cache: "no-store" }
    );
    if (res.status === 404) {
      fetchError = `Player "${username}" not found. Try syncing from the homepage first.`;
    } else if (!res.ok) {
      fetchError = `Failed to load patterns (${res.status}).`;
    } else {
      data = await res.json();
    }
  } catch {
    fetchError = "Could not reach the chess-coach API. Is it running?";
  }

  const patterns = data?.patterns ?? [];
  const maxCount = patterns.length > 0 ? patterns[0].count : 1;
  const phaseCounts = data?.phase_counts ?? {};
  const phaseTotal = Object.values(phaseCounts).reduce((a, b) => a + b, 0);
  const phaseOrder = ["opening", "middlegame", "endgame"] as const;

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="mb-8">
        <Link
          href={`/players/${encodeURIComponent(username)}`}
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          ← {username}
        </Link>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">Mistake Patterns</h1>
        <p className="mt-1 text-sm text-neutral-400">
          Your most frequent error motifs. Each count is the number of games
          where the pattern appeared at least once.
        </p>
      </div>

      <AnalyzeAllButton username={username} />

      {fetchError && (
        <p className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {fetchError}
        </p>
      )}

      {data && patterns.length === 0 && (
        <div className="rounded-lg border border-neutral-800 px-6 py-12 text-center text-neutral-500">
          <p className="text-lg">No patterns found yet.</p>
          <p className="mt-2 text-sm">
            Click <span className="font-semibold text-neutral-300">Analyze games</span> above
            to run Stockfish on a batch and surface your motifs here.
          </p>
        </div>
      )}

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

      {patterns.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {patterns.map((p, i) => {
            const label = MOTIF_LABELS[p.motif] ?? p.motif;
            const desc = MOTIF_DESC[p.motif] ?? "";
            const barPct = Math.round((p.count / maxCount) * 100);
            return (
              <div
                key={p.motif}
                className={`flex flex-col rounded-xl border p-5 ${motifColor(i)}`}
              >
                <div className="mb-3 flex items-start justify-between gap-2">
                  <h2 className="text-base font-semibold leading-tight">{label}</h2>
                  <span className="shrink-0 rounded-full bg-neutral-800 px-2.5 py-0.5 text-xs font-bold text-neutral-200">
                    {p.count} {p.count === 1 ? "game" : "games"}
                  </span>
                </div>

                {desc && (
                  <p className="mb-4 text-xs text-neutral-400 leading-relaxed">{desc}</p>
                )}

                {/* Frequency bar */}
                <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                  <div
                    className="h-full rounded-full bg-neutral-300"
                    style={{ width: `${barPct}%` }}
                  />
                </div>

                <div className="mt-auto flex items-center justify-between gap-2">
                  {p.last_seen_game_id && (
                    <Link
                      href={`/players/${encodeURIComponent(username)}/games/${p.last_seen_game_id}`}
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
      )}
    </main>
  );
}

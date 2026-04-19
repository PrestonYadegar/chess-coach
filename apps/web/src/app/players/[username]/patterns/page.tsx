import Link from "next/link";

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
}

const MOTIF_LABELS: Record<string, string> = {
  hanging_piece: "Hanging Piece",
  fork_missed: "Fork Missed",
  back_rank: "Back Rank",
  pin_missed: "Pin Missed",
  discovered_attack: "Discovered Attack",
  overloaded_piece: "Overloaded Piece",
  king_safety: "King Safety",
  endgame_technique: "Endgame Technique",
  opening_principle: "Opening Principle",
};

const MOTIF_DESC: Record<string, string> = {
  hanging_piece: "Left a piece undefended or missed capturing a free piece.",
  fork_missed: "Missed a fork opportunity that wins material.",
  back_rank: "Vulnerable or missed a back-rank mating threat.",
  pin_missed: "Missed pinning an opponent's piece to win material.",
  discovered_attack: "Missed or fell victim to a discovered attack.",
  overloaded_piece: "A piece was overloaded and couldn't defend everything.",
  king_safety: "King was exposed or castling was neglected.",
  endgame_technique: "Inaccurate technique in the endgame phase.",
  opening_principle: "Violated an opening principle (development, center control, etc.).",
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
          Your most frequent error motifs across all analyzed games.
        </p>
      </div>

      {fetchError && (
        <p className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {fetchError}
        </p>
      )}

      {data && patterns.length === 0 && (
        <div className="rounded-lg border border-neutral-800 px-6 py-12 text-center text-neutral-500">
          <p className="text-lg">No patterns found yet.</p>
          <p className="mt-2 text-sm">
            Analyze some games first —{" "}
            <Link
              href={`/players/${encodeURIComponent(username)}`}
              className="underline hover:text-neutral-300"
            >
              go to your game list
            </Link>{" "}
            and click into a game to run analysis.
          </p>
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
                    {p.count}×
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

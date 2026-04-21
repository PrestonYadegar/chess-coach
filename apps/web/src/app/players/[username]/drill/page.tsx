import Link from "next/link";
import DrillBoard from "./DrillBoard";

export default async function DrillPage({
  params,
  searchParams,
}: {
  params: { username: string };
  searchParams: { motif?: string };
}) {
  const username = decodeURIComponent(params.username);
  const motif = searchParams.motif;

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="mb-8">
        <Link
          href={`/players/${encodeURIComponent(username)}/patterns`}
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          ← Patterns
        </Link>
        <h1 className="mt-2 text-3xl font-bold tracking-tight">Puzzle Drill</h1>
        <p className="mt-1 text-sm text-neutral-400">
          {motif
            ? `Focused on: ${motif.replace(/_/g, " ")}`
            : "Mixed puzzles matching your top mistake patterns."}
        </p>
      </div>

      <DrillBoard username={username} initialMotif={motif} />
    </main>
  );
}

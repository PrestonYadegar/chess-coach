import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
import type { CandidateLine } from "@/lib/types";

interface Options {
  multipv: number;
  depth?: number;
  debounceMs?: number;
  enabled?: boolean;
}

// Fetch engine candidate lines for a FEN from POST /positions/evaluate, with an
// optional debounce and a stale-response guard (responses for an old FEN are
// dropped). When disabled or fen is null, lines are cleared.
export function useEngineEval(
  fen: string | null,
  { multipv, depth = 18, debounceMs = 0, enabled = true }: Options
): { lines: CandidateLine[]; loading: boolean } {
  const [lines, setLines] = useState<CandidateLine[]>([]);
  const [loading, setLoading] = useState(false);
  const fetchRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || !fen) {
      setLines([]);
      return;
    }

    const run = () => {
      const target = fen;
      fetchRef.current = target;
      setLoading(true);
      fetch(`${API_URL}/positions/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen: target, depth, multipv }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (fetchRef.current !== target) return; // stale
          setLines((data.lines as CandidateLine[]) ?? []);
        })
        .catch(() => {
          if (fetchRef.current !== target) return;
          setLines([]);
        })
        .finally(() => {
          if (fetchRef.current === target) setLoading(false);
        });
    };

    if (debounceMs > 0) {
      const timer = setTimeout(run, debounceMs);
      return () => clearTimeout(timer);
    }
    run();
  }, [fen, enabled, multipv, depth, debounceMs]);

  return { lines, loading };
}

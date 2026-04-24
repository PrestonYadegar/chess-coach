import type { CandidateLine } from "./types";

// Centipawn eval magnitude past which we clamp for display purposes.
export const CLAMP = 1000;

export function clampCp(cp: number): number {
  return Math.max(-CLAMP, Math.min(CLAMP, cp));
}

// Format a centipawn eval (white POV) as a signed pawn value, e.g. "+1.4".
export function evalLabel(evalCp: number | null | undefined): string {
  if (evalCp == null) return "—";
  const abs = Math.abs(evalCp);
  const sign = evalCp > 0 ? "+" : evalCp < 0 ? "−" : "";
  const pawns = (abs / 100).toFixed(1);
  return `${sign}${pawns}`;
}

// Label for a candidate line — mate scores take precedence over centipawns.
export function candidateEvalLabel(line: CandidateLine): string {
  if (line.mate != null) return line.mate > 0 ? `M${line.mate}` : `-M${Math.abs(line.mate)}`;
  return evalLabel(line.eval_cp);
}

// Convert centipawn eval (white POV) to white's percentage of the bar (0–100).
// Positive eval = white winning. Clamped to ±CLAMP cp.
export function evalToWhitePct(evalCp: number | null | undefined): number {
  if (evalCp == null) return 50;
  const clamped = clampCp(evalCp);
  return 50 + (clamped / CLAMP) * 45; // 5%–95% range so colors always visible
}

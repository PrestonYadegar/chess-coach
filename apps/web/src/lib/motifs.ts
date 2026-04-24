// Human-readable labels for motif tags.
export const MOTIF_LABELS: Record<string, string> = {
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

// Title-cased label for a motif tag, falling back to a humanized form.
export function formatMotif(tag: string): string {
  return MOTIF_LABELS[tag] ?? tag.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Lightweight humanization (underscores → spaces) used where lower-case +
// CSS `capitalize` styling handles casing.
export function prettyMotif(tag: string): string {
  return tag.replace(/_/g, " ");
}

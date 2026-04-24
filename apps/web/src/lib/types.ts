// Shared frontend types.

// Structure of each motif's evidence as stored in motif_details JSON.
export interface MotifEvidence {
  squares?: string[];
  pieces?: string[];
  by_move?: string;
  line?: string[];
  exploiting?: string;
}

// A candidate move/line from POST /positions/evaluate.
export interface CandidateLine {
  rank: number;
  move_uci: string;
  move_san: string;
  eval_cp: number | null;
  mate: number | null;
  pv_uci: string[];
  pv_san: string[];
}

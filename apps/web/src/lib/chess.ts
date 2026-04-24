import { Chess } from "chess.js";

// Parse a UCI move into the { from, to, promotion } object chess.js expects.
function uciMove(uci: string): { from: string; to: string; promotion?: string } {
  return {
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    promotion: uci.length > 4 ? uci.slice(4, 5) : undefined,
  };
}

// Apply a UCI move to a Chess instance (mutates it); return the move SAN, or
// null on an illegal move.
export function applyUci(chess: Chess, uci: string): string | null {
  try {
    const m = chess.move(uciMove(uci));
    return m.san;
  } catch {
    return null;
  }
}

// Convert a UCI move to SAN given the position it was played from. Returns the
// original uci unchanged on failure (or when either input is null).
export function uciToSan(fen: string | null, uci: string | null): string | null {
  if (!fen || !uci) return uci;
  try {
    const c = new Chess(fen);
    const m = c.move(uciMove(uci));
    return m.san;
  } catch {
    return uci;
  }
}

// Extract from/to squares from a UCI move string (e.g. "e2e4" → ["e2","e4"]).
export function uciSquares(uci: string | null | undefined): [string, string] | null {
  if (!uci || uci.length < 4) return null;
  return [uci.slice(0, 2), uci.slice(2, 4)];
}

// Determine the side to move ("white" | "black") from a FEN.
export function sideFromFen(fen: string): "white" | "black" {
  const parts = fen.split(" ");
  return parts[1] === "b" ? "black" : "white";
}

// Apply a sequence of UCI moves starting from a FEN; return the resulting FEN,
// or null if any move is illegal.
export function fenAfterUcis(startFen: string, ucis: string[]): string | null {
  try {
    const chess = new Chess(startFen);
    for (const uci of ucis) chess.move(uciMove(uci));
    return chess.fen();
  } catch {
    return null;
  }
}

// Build the list of FENs for every position in a PGN (including the start).
export function buildPositions(pgn: string): string[] {
  const chess = new Chess();
  try {
    chess.loadPgn(pgn);
  } catch {
    return [new Chess().fen()];
  }
  const history = chess.history({ verbose: true });
  const positions: string[] = [];
  const game = new Chess();
  positions.push(game.fen());
  for (const move of history) {
    game.move(move.san);
    positions.push(game.fen());
  }
  return positions;
}

// Build the SAN move list for a PGN.
export function buildMoveList(pgn: string): string[] {
  const chess = new Chess();
  try {
    chess.loadPgn(pgn);
  } catch {
    return [];
  }
  return chess.history();
}

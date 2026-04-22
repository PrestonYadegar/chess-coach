import React from "react";

// Small mini-diagram icons for each mistake motif: a tiny board fragment with
// Unicode piece glyphs and directional arrows illustrating the tactic.
// viewBox is a 40×40 board of 10px cells (4×4 grid). Helpers below place
// checker squares, piece glyphs, and arrows on that grid.

const C = 10; // cell size
const LIGHT = "#b9c4a0";
const DARK = "#6f8a5b";

function cell(cx: number, cy: number, key: string) {
  const dark = (cx + cy) % 2 === 1;
  return (
    <rect
      key={key}
      x={cx * C}
      y={cy * C}
      width={C}
      height={C}
      fill={dark ? DARK : LIGHT}
    />
  );
}

// A row/region of cells, e.g. board([[0,0],[1,0],[2,0]])
function board(cells: [number, number][]) {
  return cells.map(([x, y]) => cell(x, y, `c${x}-${y}`));
}

// Piece glyph centered in cell (cx,cy). white=true → light fill + dark outline.
function piece(cx: number, cy: number, ch: string, white = false, key = "p") {
  return (
    <text
      key={key}
      x={cx * C + C / 2}
      y={cy * C + C / 2 + 0.5}
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={9}
      fill={white ? "#f8f8f8" : "#111"}
      stroke={white ? "#111" : "none"}
      strokeWidth={white ? 0.3 : 0}
    >
      {ch}
    </text>
  );
}

// Arrow from cell-center to cell-center (grid coords, may be fractional).
function arrow(x1: number, y1: number, x2: number, y2: number, color: string, key = "a") {
  return (
    <line
      key={key}
      x1={x1 * C + C / 2}
      y1={y1 * C + C / 2}
      x2={x2 * C + C / 2}
      y2={y2 * C + C / 2}
      stroke={color}
      strokeWidth={1.4}
      markerEnd={`url(#mi-arrow-${color === RED ? "r" : color === GRN ? "g" : "n"})`}
    />
  );
}

const RED = "#ef4444";
const GRN = "#34d399";
const NEU = "#e5e7eb";

// Glyphs (solid set renders crisp at tiny sizes)
const K = "♚", Q = "♛", R = "♜", B = "♝", N = "♞", P = "♟";

function content(motif: string): React.ReactNode {
  switch (motif) {
    case "skewer_missed":
      // bishop skewers king → queen along a diagonal-ish row
      return (
        <>
          {board([[0, 1], [1, 1], [2, 1], [3, 1]])}
          {piece(0, 1, B, true, "b")}
          {piece(2, 1, K, false, "k")}
          {piece(3, 1, Q, false, "q")}
          {arrow(0.3, 1, 3, 1, NEU)}
        </>
      );
    case "fork_missed":
      // knight forks two pieces
      return (
        <>
          {board([[1, 1], [1, 2], [3, 0], [3, 2]])}
          {piece(1, 2, N, true, "n")}
          {piece(3, 0, K, false, "k")}
          {piece(3, 2, R, false, "r")}
          {arrow(1, 2, 2.7, 0.2, NEU, "a1")}
          {arrow(1, 2, 2.7, 2, NEU, "a2")}
        </>
      );
    case "pin_missed":
      // bishop pins knight to king behind
      return (
        <>
          {board([[0, 1], [1, 1], [2, 1], [3, 1]])}
          {piece(0, 1, B, true, "b")}
          {piece(2, 1, N, false, "n")}
          {piece(3, 1, K, false, "k")}
          {arrow(0.3, 1, 3, 1, NEU)}
        </>
      );
    case "hanging_piece":
      // an undefended piece attacked (red arrow), warning
      return (
        <>
          {board([[1, 1], [2, 1], [1, 2], [2, 2]])}
          {piece(2, 1, R, true, "r")}
          {arrow(0.5, 0.4, 1.8, 1, RED)}
          {piece(2.6, 2.3, "!", false, "ex")}
        </>
      );
    case "back_rank":
      // king on back rank behind own pawns, rook mates along rank
      return (
        <>
          {board([[0, 0], [1, 0], [2, 0], [3, 0], [1, 1], [2, 1]])}
          {piece(2, 0, K, true, "k")}
          {piece(1, 1, P, true, "p1")}
          {piece(2, 1, P, true, "p2")}
          {piece(0, 0, R, false, "r")}
          {arrow(0.3, 0, 1.8, 0, RED)}
        </>
      );
    case "discovered_attack":
      // a piece steps aside revealing a rook's attack
      return (
        <>
          {board([[0, 1], [1, 1], [2, 1], [3, 1]])}
          {piece(0, 1, R, true, "r")}
          {piece(1, 0.2, N, true, "n")}
          {arrow(1, 1, 1, 0.4, GRN, "mv")}
          {piece(3, 1, Q, false, "q")}
          {arrow(0.3, 1, 3, 1, NEU, "ln")}
        </>
      );
    case "overloaded_piece":
      // one defender pulled two ways
      return (
        <>
          {board([[1, 1], [0, 0], [2, 0], [1, 2]])}
          {piece(1, 1, Q, true, "q")}
          {arrow(0.3, 0.3, 0.9, 0.9, RED, "a1")}
          {arrow(2.7, 0.3, 1.1, 0.9, RED, "a2")}
        </>
      );
    case "intermezzo_missed":
      // an in-between check before recapture (zigzag-ish via two arrows)
      return (
        <>
          {board([[0, 2], [1, 1], [2, 0], [2, 2]])}
          {piece(0, 2, B, true, "b")}
          {piece(2, 0, K, false, "k")}
          {arrow(0.3, 1.8, 1.8, 0.3, GRN, "chk")}
          {piece(2.6, 2.4, "+", false, "pl")}
        </>
      );
    case "only_move_missed":
      // king in check, single escape
      return (
        <>
          {board([[1, 1], [2, 1], [1, 2], [2, 2]])}
          {piece(1, 1, K, true, "k")}
          {arrow(3, 1, 1.6, 1, RED, "atk")}
          {arrow(1, 1, 2, 2, GRN, "esc")}
        </>
      );
    case "mating_net_missed":
      return (
        <>
          {board([[1, 1], [2, 1], [1, 2], [2, 2]])}
          {piece(2, 1, K, false, "k")}
          {arrow(0.4, 0.4, 1.6, 1, GRN, "a1")}
          {arrow(3, 2.6, 2.4, 1.4, GRN, "a2")}
          {piece(0.5, 2.4, "#", false, "h")}
        </>
      );
    case "mating_net_allowed":
      return (
        <>
          {board([[1, 1], [2, 1], [1, 2], [2, 2]])}
          {piece(1, 1, K, true, "k")}
          {arrow(3, 0.4, 1.6, 1, RED, "a1")}
          {arrow(0.4, 2.6, 1, 1.6, RED, "a2")}
          {piece(2.6, 2.4, "#", false, "h")}
        </>
      );
    case "king_safety":
      // exposed king, broken pawn shield
      return (
        <>
          {board([[0, 1], [1, 1], [2, 1], [1, 0]])}
          {piece(1, 1, K, true, "k")}
          {piece(0, 0, P, true, "p1")}
          {piece(2, 0, P, true, "p2")}
          {arrow(3, 0.2, 1.4, 0.9, RED, "atk")}
        </>
      );
    case "pawn_structure":
      // doubled / isolated pawns
      return (
        <>
          {board([[1, 0], [1, 1], [1, 2], [3, 1]])}
          {piece(1, 0, P, true, "p1")}
          {piece(1, 1, P, true, "p2")}
          {piece(3, 1, P, true, "p3")}
        </>
      );
    case "endgame_technique":
      // king + pawn endgame
      return (
        <>
          {board([[1, 0], [1, 1], [1, 2], [2, 2]])}
          {piece(1, 0, K, true, "k")}
          {piece(1, 1, P, true, "p")}
          {piece(2, 2, K, false, "k2")}
        </>
      );
    case "opening_principle":
      // develop a knight toward the center
      return (
        <>
          {board([[1, 3], [2, 2], [1, 1], [2, 1]])}
          {piece(1, 3, N, true, "n")}
          {arrow(1, 3, 2, 2, GRN, "dev")}
        </>
      );
    default:
      return (
        <>
          {board([[1, 1], [2, 1], [1, 2], [2, 2]])}
          {piece(1.5, 1.5, "?", false, "q")}
        </>
      );
  }
}

export default function MotifIcon({
  motif,
  size = 34,
  className,
}: {
  motif: string;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={className}
      aria-hidden
    >
      <defs>
        {[
          ["n", NEU],
          ["r", RED],
          ["g", GRN],
        ].map(([id, color]) => (
          <marker
            key={id}
            id={`mi-arrow-${id}`}
            viewBox="0 0 10 10"
            refX={8}
            refY={5}
            markerWidth={4}
            markerHeight={4}
            orient="auto-start-reverse"
          >
            <path d="M0 0 L10 5 L0 10 z" fill={color} />
          </marker>
        ))}
      </defs>
      <rect x={0} y={0} width={40} height={40} rx={4} fill="#3a3a3a" />
      {content(motif)}
    </svg>
  );
}

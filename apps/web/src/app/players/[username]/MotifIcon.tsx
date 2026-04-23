import React from "react";

// Simple, glanceable abstract icons for each mistake motif. Bold single-concept
// line symbols (not busy board diagrams) so they read at card size without
// zooming. viewBox is a plain 40×40 canvas.

const NEU = "#e5e7eb";
const RED = "#f87171";
const GRN = "#34d399";
const AMB = "#fbbf24";

interface Opt {
  color?: string;
  w?: number;
  fill?: string;
  head?: boolean;
  size?: number;
  weight?: number;
}

function ln(x1: number, y1: number, x2: number, y2: number, o: Opt = {}, key = "l") {
  const color = o.color ?? NEU;
  const id = color === RED ? "r" : color === GRN ? "g" : "n";
  return (
    <line
      key={key}
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={color}
      strokeWidth={o.w ?? 2.4}
      strokeLinecap="round"
      markerEnd={o.head ? `url(#mi-${id})` : undefined}
    />
  );
}

function cir(cx: number, cy: number, r: number, o: Opt = {}, key = "c") {
  return (
    <circle
      key={key}
      cx={cx}
      cy={cy}
      r={r}
      stroke={o.color ?? NEU}
      strokeWidth={o.w ?? 2.4}
      fill={o.fill ?? "none"}
    />
  );
}

function pth(d: string, o: Opt = {}, key = "p") {
  return (
    <path
      key={key}
      d={d}
      stroke={o.color ?? NEU}
      strokeWidth={o.w ?? 2.4}
      fill={o.fill ?? "none"}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

function sym(x: number, y: number, ch: string, o: Opt = {}, key = "s") {
  return (
    <text
      key={key}
      x={x}
      y={y}
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={o.size ?? 16}
      fontWeight={o.weight ?? 700}
      fill={o.color ?? NEU}
    >
      {ch}
    </text>
  );
}

function content(motif: string): React.ReactNode {
  switch (motif) {
    case "hanging_piece": // warning triangle
      return (
        <>
          {pth("M20 9 L32 30 L8 30 Z", { color: AMB }, "t")}
          {ln(20, 16, 20, 23, { color: AMB, w: 2.6 }, "ex")}
          {cir(20, 27, 0.4, { color: AMB, fill: AMB, w: 2 }, "dot")}
        </>
      );
    case "fork_missed": // branching arrow (one origin → two heads)
      return (
        <>
          {ln(20, 32, 20, 22, {}, "stem")}
          {ln(20, 22, 11, 11, { head: true }, "b1")}
          {ln(20, 22, 29, 11, { head: true }, "b2")}
        </>
      );
    case "skewer_missed": // straight arrow through two pieces
      return (
        <>
          {ln(6, 20, 36, 20, { head: true }, "ar")}
          {cir(13, 20, 3, { fill: "#3f4045" }, "p1")}
          {cir(21, 20, 3, { fill: "#3f4045" }, "p2")}
        </>
      );
    case "pin_missed": // a pushpin / thumbtack
      return (
        <>
          <ellipse cx={20} cy={12} rx={8} ry={4} fill={NEU} />
          {ln(13, 17, 27, 17, { w: 2.6 }, "base")}
          {ln(20, 17, 20, 33, { w: 2.6 }, "needle")}
        </>
      );
    case "discovered_attack": // surprise: ? with a +
      return (
        <>
          {sym(18, 21, "?", { size: 24 }, "q")}
          {sym(31, 11, "+", { size: 14, color: GRN }, "plus")}
        </>
      );
    case "overloaded_piece": // two arrows converging on one piece
      return (
        <>
          {ln(8, 9, 17, 18, { color: RED, head: true }, "a1")}
          {ln(32, 9, 23, 18, { color: RED, head: true }, "a2")}
          {cir(20, 24, 3.2, { color: RED, fill: RED, w: 0 }, "dot")}
        </>
      );
    case "intermezzo_missed": // in-between: scattered + × ○ (equal size)
      return (
        <>
          {sym(11, 14, "+", { size: 18, color: GRN }, "pl")}
          {sym(30, 14, "×", { size: 18, color: RED }, "x")}
          {cir(20, 29, 5.5, { color: NEU, w: 2.4 }, "o")}
        </>
      );
    case "only_move_missed": // bullseye: the single right square
      return (
        <>
          {cir(20, 20, 11, {}, "o1")}
          {cir(20, 20, 5, {}, "o2")}
          {cir(20, 20, 1, { fill: NEU, w: 1.5 }, "o3")}
        </>
      );
    case "mating_net_missed": // you had mate (#, green)
      return sym(20, 21, "#", { size: 26, color: GRN }, "h");
    case "mating_net_allowed": // you walked into mate (#, red)
      return sym(20, 21, "#", { size: 26, color: RED }, "h");
    case "king_safety": // a broken shield (✕ through it)
      return (
        <>
          {pth(
            "M20 8 L31 12 L31 20 C31 27 26 31 20 33 C14 31 9 27 9 20 L9 12 Z",
            { w: 2.2 },
            "shield"
          )}
          {ln(15, 16, 25, 26, { color: RED, w: 2.6 }, "x1")}
          {ln(25, 16, 15, 26, { color: RED, w: 2.6 }, "x2")}
        </>
      );
    case "pawn_structure": // fortress battlements with brickwork
      return (
        <>
          {pth(
            "M8 31 L8 18 L13 18 L13 14 L18 14 L18 18 L22 18 L22 14 L27 14 L27 18 L32 18 L32 31 Z",
            { w: 2.2 },
            "wall"
          )}
          {/* mortar courses */}
          {ln(8, 22.5, 32, 22.5, { w: 1.2 }, "h1")}
          {ln(8, 27, 32, 27, { w: 1.2 }, "h2")}
          {/* staggered vertical joints (running bond) */}
          {ln(20, 18, 20, 22.5, { w: 1.2 }, "v1")}
          {ln(15, 22.5, 15, 27, { w: 1.2 }, "v2")}
          {ln(25, 22.5, 25, 27, { w: 1.2 }, "v3")}
          {ln(20, 27, 20, 31, { w: 1.2 }, "v4")}
        </>
      );
    case "endgame_technique": // finish flag
      return (
        <>
          {ln(13, 8, 13, 32, { w: 2.4 }, "pole")}
          {pth("M13 9 L29 13 L13 18 Z", { fill: NEU }, "flag")}
        </>
      );
    case "opening_principle": // open book
      return (
        <>
          {pth("M20 13 L9 11 L9 28 L20 30 Z", {}, "left")}
          {pth("M20 13 L31 11 L31 28 L20 30 Z", {}, "right")}
        </>
      );
    case "back_rank": // boxed-in corner on the back rank, mate sliding in
      return (
        <>
          {ln(7, 31, 33, 31, { w: 2.6 }, "rank")}
          <rect
            key="box"
            x={26}
            y={23}
            width={7}
            height={8}
            stroke={NEU}
            strokeWidth={2.2}
            fill="none"
          />
          {ln(9, 26, 24, 26, { color: RED, head: true }, "mate")}
        </>
      );
    default:
      return sym(20, 20, "?", { size: 18 }, "q");
  }
}

export default function MotifIcon({
  motif,
  size = 36,
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
            id={`mi-${id}`}
            viewBox="0 0 10 10"
            refX={7}
            refY={5}
            markerWidth={3.5}
            markerHeight={3.5}
            orient="auto-start-reverse"
          >
            <path d="M0 0 L10 5 L0 10 z" fill={color} />
          </marker>
        ))}
      </defs>
      <rect x={0} y={0} width={40} height={40} rx={7} fill="#3f4045" />
      {content(motif)}
    </svg>
  );
}

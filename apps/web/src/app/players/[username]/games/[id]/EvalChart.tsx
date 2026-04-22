"use client";

import { useMemo, useRef } from "react";
import type { PlyAnalysis } from "./page";

interface Props {
  analysis: PlyAnalysis[];
  // Board cursor = position after N moves. The "current move" is ply cursor-1.
  cursor: number;
  onSeek: (ply: number) => void;
  width?: number;
  height?: number;
}

const CLAMP = 1000;
const PAD_L = 26; // gutter for y-axis labels
// cp gridlines + their labels (white-POV pawns)
const GRID: { cp: number; label: string }[] = [
  { cp: 600, label: "+6" },
  { cp: 300, label: "+3" },
  { cp: 0, label: "0" },
  { cp: -300, label: "-3" },
  { cp: -600, label: "-6" },
];

// Interactive white-POV eval graph across the whole game. Light mass above the
// 0-line = white better, dark mass below = black better. Click to jump moves.
export default function EvalChart({
  analysis,
  cursor,
  onSeek,
  width = 480,
  height = 110,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const { points, maxPly } = useMemo(() => {
    const byPly = new Map<number, PlyAnalysis>();
    for (const r of analysis) byPly.set(r.ply, r);
    const max = analysis.reduce((m, r) => Math.max(m, r.ply), 0);
    const pts: { ply: number; cp: number; cls: string | null }[] = [];
    let last = 0;
    for (let p = 0; p <= max; p++) {
      const row = byPly.get(p);
      if (row?.eval_cp != null) last = row.eval_cp;
      pts.push({
        ply: p,
        cp: Math.max(-CLAMP, Math.min(CLAMP, last)),
        cls: row?.classification ?? null,
      });
    }
    return { points: pts, maxPly: max };
  }, [analysis]);

  if (points.length < 2) return null;

  const mid = height / 2;
  const plotW = width - PAD_L;
  const n = points.length;
  // x for the position after move at index i (ply i). Start (no moves) at PAD_L.
  const xOf = (i: number) => PAD_L + ((i + 1) / (n + 1)) * plotW;
  const yOf = (cp: number) =>
    mid - (Math.max(-CLAMP, Math.min(CLAMP, cp)) / CLAMP) * mid;

  const coords = points.map((pt, i) => [xOf(i), yOf(pt.cp)] as [number, number]);
  const line =
    `M${PAD_L} ${mid} ` +
    coords.map(([x, y]) => `L${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  // Area between the curve and the 0-line; split by clip into white/black halves.
  const lastX = xOf(n - 1);
  const area = `${line} L${lastX.toFixed(1)} ${mid} L${PAD_L} ${mid} Z`;

  const activePly = cursor - 1;
  const activeIdx = activePly >= 0 && activePly <= maxPly ? activePly : null;

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const xPx = ((e.clientX - rect.left) / rect.width) * width;
    const x = Math.max(0, xPx - PAD_L);
    // invert xOf: x = (i+1)/(n+1)*plotW  →  i = x/plotW*(n+1) - 1
    const i = Math.round((x / plotW) * (n + 1) - 1);
    onSeek(Math.max(0, Math.min(maxPly, i)));
  }

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      onClick={handleClick}
      className="cursor-pointer rounded border border-neutral-800"
      style={{ background: "#262626" }}
    >
      <defs>
        <clipPath id="evalUpper">
          <rect x={PAD_L} y={0} width={plotW} height={mid} />
        </clipPath>
        <clipPath id="evalLower">
          <rect x={PAD_L} y={mid} width={plotW} height={height - mid} />
        </clipPath>
      </defs>

      {/* split fill: white-advantage (above) light, black-advantage (below) dark */}
      <path d={area} fill="#ededed" clipPath="url(#evalUpper)" />
      <path d={area} fill="#0a0a0a" clipPath="url(#evalLower)" />

      {/* gridlines + labels */}
      {GRID.map(({ cp, label }) => {
        const y = yOf(cp);
        const zero = cp === 0;
        return (
          <g key={cp}>
            <line
              x1={PAD_L}
              y1={y}
              x2={width}
              y2={y}
              stroke={zero ? "#737373" : "#525252"}
              strokeWidth={zero ? 0.9 : 0.5}
              strokeDasharray={zero ? "3 3" : "2 4"}
            />
            <text
              x={PAD_L - 4}
              y={y + 3}
              textAnchor="end"
              fontSize={8}
              fill="#a3a3a3"
            >
              {label}
            </text>
          </g>
        );
      })}

      {/* eval curve */}
      <path d={line} fill="none" stroke="#6b7280" strokeWidth={1.5} strokeLinejoin="round" />

      {/* blunder / mistake markers */}
      {points.map((pt, i) =>
        pt.cls === "blunder" || pt.cls === "mistake" ? (
          <circle
            key={i}
            cx={xOf(i)}
            cy={yOf(pt.cp)}
            r={2.5}
            fill={pt.cls === "blunder" ? "#ef4444" : "#f97316"}
            stroke="#262626"
            strokeWidth={0.5}
          />
        ) : null
      )}

      {/* current-move indicator */}
      {activeIdx != null && (
        <>
          <line
            x1={xOf(activeIdx)}
            y1={0}
            x2={xOf(activeIdx)}
            y2={height}
            stroke="#34d399"
            strokeWidth={1}
          />
          <circle cx={xOf(activeIdx)} cy={yOf(points[activeIdx].cp)} r={3.5} fill="#34d399" />
        </>
      )}
    </svg>
  );
}

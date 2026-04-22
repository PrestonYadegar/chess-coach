// Tiny presentational eval sparkline (no interactivity → server-renderable).
// series is white-POV centipawns (clamped ±1000) by ply; we flip to the
// viewing player's POV so "up" always means "good for them".

interface Props {
  series: (number | null)[];
  playerIsWhite: boolean;
  width?: number;
  height?: number;
}

const CLAMP = 1000;

export default function EvalSparkline({
  series,
  playerIsWhite,
  width = 120,
  height = 34,
}: Props) {
  const pts = series.filter((v): v is number => v != null);
  if (pts.length < 2) {
    return <div className="text-xs text-neutral-600">—</div>;
  }

  const flipped = series.map((v) => (v == null ? null : playerIsWhite ? v : -v));
  const n = flipped.length;
  const mid = height / 2;

  // cp → y (0 cp at mid, +CLAMP at top, -CLAMP at bottom)
  const yOf = (cp: number) => mid - (Math.max(-CLAMP, Math.min(CLAMP, cp)) / CLAMP) * mid;
  const xOf = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * width);

  // Build a path, carrying the last known value across null (mate) gaps.
  let last = 0;
  const coords: [number, number][] = flipped.map((v, i) => {
    if (v != null) last = v;
    return [xOf(i), yOf(last)];
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width} ${mid} L0 ${mid} Z`;

  const lastVal = (() => {
    for (let i = flipped.length - 1; i >= 0; i--) if (flipped[i] != null) return flipped[i]!;
    return 0;
  })();
  const good = lastVal >= 0;
  const stroke = good ? "#34d399" : "#f87171";
  const fill = good ? "rgba(52,211,153,0.12)" : "rgba(248,113,113,0.12)";

  return (
    <svg width={width} height={height} className="block" aria-hidden>
      <line x1={0} y1={mid} x2={width} y2={mid} stroke="#404040" strokeWidth={0.5} strokeDasharray="2 2" />
      <path d={area} fill={fill} stroke="none" />
      <path d={line} fill="none" stroke={stroke} strokeWidth={1.25} strokeLinejoin="round" />
    </svg>
  );
}

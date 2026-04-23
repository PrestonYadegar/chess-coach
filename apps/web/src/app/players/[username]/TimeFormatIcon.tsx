// Small monochrome glyphs evoking Chess.com's time-class icons:
// Bullet → a bullet/projectile, Blitz → lightning, Rapid → stopwatch,
// Classical → hourglass, Daily → sun. Unknown formats fall back to a dot.

const COLORS: Record<string, string> = {
  Bullet: "text-rose-400",
  Blitz: "text-amber-400",
  Rapid: "text-emerald-400",
  Classical: "text-sky-400",
  Daily: "text-orange-400",
};

function Glyph({ format }: { format: string }) {
  const cls = "h-3.5 w-3.5";
  switch (format) {
    case "Bullet":
      // A bullet projectile: ogive nose pointing right, with motion lines.
      return (
        <svg viewBox="0 0 24 24" className={cls} aria-hidden="true">
          <path
            d="M8 7h4c4 0 6.5 2.2 6.5 5S16 17 12 17H8z"
            fill="currentColor"
          />
          <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M2 8.5h2.5" />
            <path d="M1.5 12h2.5" />
            <path d="M2 15.5h2.5" />
          </g>
        </svg>
      );
    case "Blitz":
      // Lightning bolt
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="currentColor" aria-hidden="true">
          <path d="M13 2 4 14h6l-1 8 9-12h-6z" />
        </svg>
      );
    case "Rapid":
      // Stopwatch
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="13" r="8" />
          <path d="M12 13V8M9 2h6M12 2v3" />
        </svg>
      );
    case "Classical":
      // Hourglass
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 3h12M6 21h12M7 3c0 5 10 5 10 9s-10 4-10 9M17 3c0 5-10 5-10 9" />
        </svg>
      );
    case "Daily":
      // Sun
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 24 24" className={cls} fill="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="5" />
        </svg>
      );
  }
}

export default function TimeFormatIcon({ format }: { format: string }) {
  return (
    <span className={`inline-flex shrink-0 ${COLORS[format] ?? "text-neutral-400"}`}>
      <Glyph format={format} />
    </span>
  );
}

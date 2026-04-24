// Breadcrumb shown while in "explore mode": lists the SAN moves played into the
// side-line and offers a button to return to the main position. Used by both
// the game viewer and the drill board (which differ only in the return label).

interface Props {
  sanLine: string[];
  onReturn: () => void;
  returnLabel: string;
  className?: string;
}

export default function ExploreBreadcrumb({ sanLine, onReturn, returnLabel, className }: Props) {
  return (
    <div className={`flex flex-col gap-1.5${className ? ` ${className}` : ""}`}>
      {sanLine.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1 rounded border border-violet-500/20 bg-violet-500/5 px-2 py-1.5">
          <span className="text-xs text-violet-400 font-semibold mr-1">Exploring:</span>
          {sanLine.map((san, i) => (
            <span key={i} className="font-mono text-xs rounded bg-neutral-800 px-1.5 py-0.5 text-violet-200">
              {san}
            </span>
          ))}
          <button onClick={onReturn} className="ml-auto text-xs text-neutral-500 hover:text-neutral-300 underline">
            {returnLabel}
          </button>
        </div>
      ) : (
        <p className="text-xs text-center text-violet-400/70">
          Drag pieces to explore alternative lines
        </p>
      )}
    </div>
  );
}

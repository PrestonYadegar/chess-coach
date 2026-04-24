"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

interface OpeningOption {
  name: string;
  games: number;
  moves: string | null;
}

interface AvailableFilters {
  openings: OpeningOption[];
  time_formats: string[];
  colors: string[];
}

interface FilterBarProps {
  available: AvailableFilters;
  activeOpening: string;
  activeTimeFormat: string;
  activeColor: string;
}

export default function FilterBar({
  available,
  activeOpening,
  activeTimeFormat,
  activeColor,
}: FilterBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const isActive = activeOpening || activeTimeFormat || activeColor;

  const buildHref = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      // When filter changes, reset page
      params.delete("page");
      for (const [k, v] of Object.entries(updates)) {
        if (v) {
          params.set(k, v);
        } else {
          params.delete(k);
        }
      }
      return `${pathname}?${params.toString()}`;
    },
    [pathname, searchParams]
  );

  function handleChange(key: string, value: string) {
    const href = buildHref({ [key]: value });
    router.push(href);
  }

  function clearAll() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("opening");
    params.delete("time_format");
    params.delete("color");
    params.delete("page");
    router.push(`${pathname}?${params.toString()}`);
  }

  return (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      {/* Opening select */}
      {available.openings.length > 0 && (
        <select
          value={activeOpening}
          onChange={(e) => handleChange("opening", e.target.value)}
          // Fixed width so reordering by count (which moves longer names in/out
          // of view) doesn't make the control jump around. Long names truncate.
          // appearance-none + bg-image chevron so we control its padding exactly.
          className="w-56 truncate rounded-lg border border-neutral-700 bg-neutral-900 bg-[length:14px_14px] bg-[right_0.625rem_center] bg-no-repeat py-1.5 pl-3 pr-8 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-neutral-500"
          style={{
            appearance: "none",
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23a3a3a3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E\")",
          }}
        >
          <option value="">All openings</option>
          {available.openings.map((o) => (
            <option key={o.name} value={o.name} title={o.moves ?? undefined}>
              {o.name} ({o.games})
            </option>
          ))}
        </select>
      )}

      {/* Time format select */}
      {available.time_formats.length > 0 && (
        <select
          value={activeTimeFormat}
          onChange={(e) => handleChange("time_format", e.target.value)}
          className="rounded-lg border border-neutral-700 bg-neutral-900 bg-[length:14px_14px] bg-[right_0.625rem_center] bg-no-repeat py-1.5 pl-3 pr-8 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-neutral-500"
          style={{
            appearance: "none",
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23a3a3a3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E\")",
          }}
        >
          <option value="">All formats</option>
          {available.time_formats.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      )}

      {/* Color buttons */}
      <div className="flex gap-1">
        {(["", "white", "black"] as const).map((c) => (
          <button
            key={c || "all"}
            onClick={() => handleChange("color", c)}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              activeColor === c
                ? "border-emerald-600 bg-emerald-900/40 text-emerald-300"
                : "border-neutral-700 bg-neutral-900 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
            }`}
          >
            {c === "" ? (
              <span className="flex shrink-0 items-center" aria-hidden="true">
                <span className="h-3 w-3 rounded-full bg-neutral-50 ring-1 ring-neutral-400" />
                <span className="-ml-1.5 h-3 w-3 rounded-full bg-neutral-950 ring-1 ring-neutral-500" />
              </span>
            ) : (
              <span
                className={`inline-block h-3 w-3 shrink-0 rounded-full ring-1 ${
                  c === "white"
                    ? "bg-neutral-50 ring-neutral-400"
                    : "bg-neutral-950 ring-neutral-500"
                }`}
                aria-hidden="true"
              />
            )}
            {c === "" ? "Either" : c === "white" ? "White" : "Black"}
          </button>
        ))}
      </div>

      {/* Clear filters */}
      {isActive && (
        <button
          onClick={clearAll}
          className="ml-auto rounded-lg border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
        >
          Clear filters ×
        </button>
      )}
    </div>
  );
}

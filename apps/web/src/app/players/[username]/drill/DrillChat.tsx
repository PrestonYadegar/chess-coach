"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { API_URL } from "@/lib/api";
import type { CandidateLine } from "@/lib/types";

interface Message {
  role: "user" | "assistant";
  text: string;
}

interface Props {
  fen: string;
  candidates: CandidateLine[];
  evalCp: number | null;
  playedMove?: string;
  bestMove?: string;
  classification?: string;
  evalCpBefore?: number | null;
  evalCpAfter?: number | null;
  userColor?: "white" | "black";
  motifDetails?: Record<string, unknown>;
  inline?: boolean; // when true, always open with no toggle header
}

export default function DrillChat({ fen, candidates, evalCp, playedMove, bestMove, classification, evalCpBefore, evalCpAfter, userColor, motifDetails, inline }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen, candidates, question, eval_cp: evalCp, played_move: playedMove, best_move: bestMove, classification, eval_cp_before: evalCpBefore, eval_cp_after: evalCpAfter, user_color: userColor, motif_details: motifDetails }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      setMessages((prev) => [...prev, { role: "assistant", text: data.answer }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const messageArea = (
    <>
      {/* Message history */}
      <div className={`flex flex-col gap-3 overflow-y-auto px-4 py-3 ${inline ? "flex-1 min-h-0" : "max-h-64"}`}>
        {messages.length === 0 && (
          <p className="text-xs text-neutral-600">
            Ask about the position — e.g. &quot;Why doesn&apos;t Bb6 work?&quot; or &quot;What&apos;s the key idea here?&quot;
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm ${m.role === "user" ? "text-right" : "text-left"}`}
          >
            <div
              className={`inline-block rounded-lg px-3 py-2 ${
                m.role === "user"
                  ? "bg-neutral-800 text-neutral-200"
                  : "bg-emerald-900/30 text-emerald-100"
              }`}
            >
              {m.role === "user" ? (
                m.text
              ) : (
                <ReactMarkdown
                  components={{
                    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-emerald-200">{children}</strong>,
                    em: ({ children }) => <em className="italic text-emerald-300">{children}</em>,
                    ul: ({ children }) => <ul className="mb-2 ml-4 list-disc">{children}</ul>,
                    li: ({ children }) => <li className="mb-0.5">{children}</li>,
                  }}
                >
                  {m.text}
                </ReactMarkdown>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <p className="text-xs text-neutral-600 animate-pulse">Coach is thinking…</p>
        )}
        {error && (
          <p className="text-xs text-red-400">
            {error.includes("not configured") ? (
              <>
                LLM not configured.{" "}
                <a href="/settings" className="underline hover:text-red-300">
                  Add your API key in Settings.
                </a>
              </>
            ) : (
              error
            )}
          </p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2 border-t border-neutral-800 px-4 py-3 flex-shrink-0">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask about this position…"
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:ring-1 focus:ring-neutral-500"
        />
        <button
          onClick={send}
          disabled={!input.trim() || loading}
          className="rounded-lg bg-emerald-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </>
  );

  return (
    <div className="flex flex-col h-full" style={{ minHeight: "400px" }}>
      {messageArea}
    </div>
  );
}

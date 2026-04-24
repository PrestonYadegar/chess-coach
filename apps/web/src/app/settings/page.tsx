"use client";

import { useEffect, useState } from "react";
import { BOARD_THEMES, useBoardTheme } from "@/lib/boardTheme";
import { API_URL } from "@/lib/api";

const PROVIDERS = [
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "openai",    label: "OpenAI (GPT)" },
  { value: "gemini",    label: "Google Gemini" },
  { value: "ollama",    label: "Ollama (local)" },
] as const;

type Provider = (typeof PROVIDERS)[number]["value"];

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-base font-semibold text-neutral-200">{title}</h2>
      <p className="mt-0.5 text-sm text-neutral-400">{description}</p>
    </div>
  );
}

function Divider() {
  return <hr className="border-neutral-800" />;
}

export default function SettingsPage() {
  const [boardTheme, setBoardTheme] = useBoardTheme();

  // LLM settings — stored in backend
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [hasStoredKey, setHasStoredKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/settings/llm`)
      .then((r) => r.json())
      .then((d) => {
        if (d.provider) setProvider(d.provider as Provider);
        setHasStoredKey(!!d.has_api_key);
      })
      .catch(() => {});
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.trim() && !hasStoredKey) return;
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_URL}/settings/llm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: apiKey }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      setStatus({ ok: true, msg: "Saved." });
      setHasStoredKey(true);
      setApiKey("");
    } catch (e) {
      setStatus({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  const isOllama = provider === "ollama";

  return (
    <main className="mx-auto max-w-lg px-6 py-12">
      <a href="/" className="mb-6 inline-block text-sm text-neutral-500 hover:text-neutral-300">
        ← Home
      </a>
      <h1 className="mb-8 text-2xl font-bold tracking-tight">Settings</h1>

      <div className="flex flex-col gap-8">

        {/* ── Appearance ─────────────────────────────────────────────────── */}
        <section>
          <SectionHeader title="Appearance" description="Visual preferences applied across the app." />
          <div className="flex flex-wrap gap-3">
            {BOARD_THEMES.map((theme) => {
              const selected = boardTheme.id === theme.id;
              const cells = Array.from({ length: 16 }, (_, i) => {
                const row = Math.floor(i / 4);
                const col = i % 4;
                return (row + col) % 2 === 0 ? theme.light : theme.dark;
              });
              return (
                <button
                  key={theme.id}
                  type="button"
                  onClick={() => setBoardTheme(theme.id)}
                  className={`flex flex-col items-center gap-2 rounded-lg border-2 p-2 transition-colors ${
                    selected ? "border-emerald-500" : "border-neutral-700 hover:border-neutral-500"
                  }`}
                >
                  <div className="grid grid-cols-4 overflow-hidden rounded" style={{ width: 56, height: 56 }}>
                    {cells.map((color, i) => (
                      <div key={i} style={{ backgroundColor: color }} />
                    ))}
                  </div>
                  <span className={`text-xs font-medium ${selected ? "text-emerald-400" : "text-neutral-400"}`}>
                    {theme.label}
                  </span>
                </button>
              );
            })}
          </div>
        </section>


        <Divider />

        {/* ── AI Coach ───────────────────────────────────────────────────── */}
        <section>
          <SectionHeader
            title="AI Coach"
            description="Connect an LLM to power the in-drill coaching chat. Your API key is encrypted before being stored — it never leaves your machine in plaintext."
          />
          <form onSubmit={handleSave} className="flex flex-col gap-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-neutral-300">Provider</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value as Provider)}
                className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-1 focus:ring-neutral-500"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-medium text-neutral-300">
                {isOllama ? "Model name" : "API key"}
              </label>
              {isOllama && (
                <p className="mb-2 text-xs text-neutral-500">
                  Enter the Ollama model name (e.g. <code className="rounded bg-neutral-800 px-1">llama3.2</code>).
                  Ollama must be running locally on port 11434.
                </p>
              )}
              <input
                type={isOllama ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  hasStoredKey
                    ? isOllama ? "Update model name…" : "Enter new key to replace stored key…"
                    : isOllama ? "llama3.2" : "sk-…"
                }
                className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 placeholder-neutral-600 focus:outline-none focus:ring-1 focus:ring-neutral-500"
              />
              {hasStoredKey && (
                <p className="mt-1.5 text-xs text-emerald-500">
                  ✓ A key is already stored for this provider. Leave blank to keep it.
                </p>
              )}
            </div>

            <div className="flex items-center gap-4">
              <button
                type="submit"
                disabled={saving || (!apiKey.trim() && !hasStoredKey)}
                className="rounded-lg bg-emerald-700 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-40"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              {status && (
                <p className={`text-sm ${status.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {status.msg}
                </p>
              )}
            </div>
          </form>
        </section>

      </div>
    </main>
  );
}

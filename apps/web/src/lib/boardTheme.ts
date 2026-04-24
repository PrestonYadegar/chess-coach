"use client";

import { useEffect, useState } from "react";

export interface BoardTheme {
  id: string;
  label: string;
  dark: string;
  light: string;
}

export const BOARD_THEMES: BoardTheme[] = [
  { id: "green",  label: "Green",  dark: "#4a7c59", light: "#f0d9b5" },
  { id: "brown",  label: "Brown",  dark: "#b58863", light: "#f0d9b5" },
  { id: "blue",   label: "Blue",   dark: "#4b7399", light: "#eae9d2" },
  { id: "walnut", label: "Walnut", dark: "#8b4513", light: "#ffdead" },
];

const STORAGE_KEY = "boardTheme";
const DEFAULT_ID = "green";

export function getBoardTheme(id: string): BoardTheme {
  return BOARD_THEMES.find((t) => t.id === id) ?? BOARD_THEMES[0];
}

export function useBoardTheme(): [BoardTheme, (id: string) => void] {
  const [themeId, setThemeId] = useState<string>(DEFAULT_ID);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setThemeId(stored);
  }, []);

  function setTheme(id: string) {
    setThemeId(id);
    localStorage.setItem(STORAGE_KEY, id);
  }

  return [getBoardTheme(themeId), setTheme];
}

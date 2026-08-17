import type { Analysis, EncounterListItem } from "./types";

const base = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, options);
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

export const api = {
  encounters: () => request<EncounterListItem[]>("/encounters"),
  analyze: (id: string) => request<Analysis>(`/analyze/${encodeURIComponent(id)}`, { method: "POST" })
};

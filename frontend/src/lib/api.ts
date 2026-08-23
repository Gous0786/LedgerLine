/** Backend base path. Vite proxies /api → http://127.0.0.1:8000 in dev. */
export const API_BASE = '/api'

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

export interface Health {
  status: string
  db: string
  schema_version: string | null
  openrouter_key_present: boolean
  models: { orchestrator: string; worker: string }
}

/** Backend base path. Vite proxies /api → http://127.0.0.1:8000 in dev. */
export const API_BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export async function getJSON<T>(path: string): Promise<T> {
  return request<T>(path)
}

export interface Health {
  status: string
  db: string
  schema_version: string | null
  openrouter_key_present: boolean
  models: { orchestrator: string; worker: string }
}

// ------------------------------------------------------------- datasets --

export interface DatasetColumn {
  ordinal: number
  source_name: string
  column_name: string
  inferred_type: string
  null_count?: number
  sample?: string
}

export interface Dataset {
  id: string
  name: string
  original_name: string | null
  role: string | null
  row_count: number
  byte_size: number
  delimiter: string | null
  encoding: string | null
  status: string
  error: string | null
  created_at: string
  column_count: number
}

export type CsvRow = Record<string, string | number | null>

export interface RowsPage {
  dataset_id: string
  columns: DatasetColumn[]
  rows: CsvRow[]
  total: number
  offset: number
  limit: number
}

export interface UploadResult {
  created: Dataset[]
  failed: { file: string; error: string }[]
}

export function listDatasets() {
  return request<Dataset[]>('/datasets')
}

export function getRows(datasetId: string, offset: number, limit: number) {
  return request<RowsPage>(`/datasets/${datasetId}/rows?offset=${offset}&limit=${limit}`)
}

export function deleteDataset(datasetId: string) {
  return request<{ deleted: string }>(`/datasets/${datasetId}`, { method: 'DELETE' })
}

export function uploadCsvs(files: File[]) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return request<UploadResult>('/datasets/upload', { method: 'POST', body: form })
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

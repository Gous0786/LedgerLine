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

// ------------------------------------------------------------ proposals --

export type ProposalStatus = 'pending' | 'accepted' | 'rejected' | 'review_later'
export type Confidence = 'exact' | 'within_tolerance' | 'high' | 'unbalanced' | 'ambiguous'

export interface Proposal {
  id: number
  rule: string
  tier: number
  group_key: string
  confidence: Confidence
  status: ProposalStatus
  member_count: number
  datasets: string
  dataset_names: string[]
  balance_minor: number | null
  tolerance_minor: number
  description: string | null
  created_at: string
}

export interface ProposalMember {
  dataset_id: string
  dataset: string
  row: number
  role: string | null
  amount_minor: number | null
  /** __row of the row this one duplicates, byte for byte. Null for ordinary
   *  members. Its amount is shown but was left out of the group's sum. */
  duplicate_of: number | null
  data: Record<string, unknown> | null
}

export interface ProposalEvent {
  ts: string
  kind: string
  actor: string
  detail: string | null
}

export interface ProposalDetail extends Proposal {
  members: ProposalMember[]
  events: ProposalEvent[]
  /** Present only when a member duplicates another row of the same source. */
  duplicates: ProposalDuplicates | null
}

export interface ProposalDuplicates {
  members: number
  amount_minor: number
  /** What the group would sum to if the duplicated rows were discounted. */
  balance_without_duplicates_minor: number | null
  /** True when discounting them alone brings the group to zero. */
  explains_residual: boolean
  /** True when their amounts still count toward the balance shown. */
  counted: boolean
  rows: {
    dataset: string
    row: number
    duplicate_of: number
    amount_minor: number | null
  }[]
}

export interface ProposalSummary {
  by_status: Partial<Record<ProposalStatus, number>>
  needs_review: number
}

export function listProposals(status: ProposalStatus | '' = '', limit = 200) {
  const q = status ? `?status=${status}&limit=${limit}` : `?limit=${limit}`
  return request<Proposal[]>(`/proposals${q}`)
}

export function getProposal(id: number) {
  return request<ProposalDetail>(`/proposals/${id}`)
}

export function proposalSummary() {
  return request<ProposalSummary>('/proposals/summary')
}

export function setProposalStatus(id: number, status: ProposalStatus, note?: string) {
  return request<{ proposal_id: number; status: string }>(`/proposals/${id}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, note }),
  })
}

/** Minor units -> display string. Amounts are integers on purpose; float sums
 *  do not compare equal, so they are only converted for rendering. */
export function formatMinor(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '—'
  const neg = minor < 0
  const s = (Math.abs(minor) / 100).toFixed(2)
  return (neg ? '-' : '') + s
}

// ---------------------------------------------------------------- rules --

export interface DatasetCoverage {
  dataset: string
  dataset_id: string
  rows: number
  matched_in_any_edge: number
  matched_in_no_edge: number
}

export interface EdgeCoverage {
  edge: string
  sides: { dataset: string; dataset_id: string; rows: number; matched: number; unmatched: number }[]
}

export interface Coverage {
  datasets: DatasetCoverage[]
  edges: EdgeCoverage[]
  totals: { rows: number; matched: number; unmatched: number }
}

export function getCoverage() {
  return request<Coverage>('/coverage')
}

export interface BatchStatusResult {
  changed: number
  blocked: number
  results: {
    proposal_id: number
    status?: ProposalStatus
    blocked?: boolean
    failures?: string[]
    error?: string
  }[]
}

/** Decide several matches at once -- accepting a chain is accepting its legs.
 *  Each still passes the release gate on its own, so a partial result is the
 *  normal outcome rather than an error. */
export function setProposalStatusBatch(
  ids: number[],
  status: ProposalStatus,
  note?: string,
) {
  return request<BatchStatusResult>('/proposals/status', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ids, status, note }),
  })
}

export interface RuleTrust {
  rule: string
  status: 'unproven' | 'trusted' | 'retired'
  first_seen: string
  approved_at: string | null
  approved_by: string | null
  proposals: number
  pending: number
}

export function listRules() {
  return request<RuleTrust[]>('/rules')
}

export function trustRule(rule: string, note?: string) {
  return request<{ rule: string; status: string; released: number }>(
    `/rules/${encodeURIComponent(rule)}/trust`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    },
  )
}

// --------------------------------------------------------- transactions --

export interface TxLeg {
  proposal_id: number
  group_key: string
  rule: string
  tier: number
  confidence: Confidence
  status: ProposalStatus
  balance_minor: number | null
  tolerance_minor: number
  is_batch: boolean
  batch_size: number
  members: { dataset: string; dataset_id: string; row: number }[]
}

export type TxState = 'reconciled' | 'pending' | 'exception' | 'incomplete' | 'unmatched'

export type HopState = 'matched' | 'tolerance' | 'unchecked' | 'off' | 'ambiguous' | 'missing'

export interface TxHop {
  from: string
  to: string
  state: HopState
  balance_minor?: number | null
  proposal_id?: number
  is_batch?: boolean
  batch_size?: number
  duplicate_in?: string[]
}

export interface Transaction {
  key: string
  spine_row: number
  data: Record<string, unknown>
  state: TxState
  leg_count: number
  expected_legs: number
  legs: TxLeg[]
  hops: TxHop[]
  reason: string | null
}

export interface TransactionsView {
  spine: { dataset_id: string; name: string; reason?: string; origin?: string }
  stages: string[]
  modal_legs: number
  transactions: Transaction[]
  leftovers: { dataset: string; dataset_id: string; count: number; rows: Record<string, unknown>[] }[]
  counts: Partial<Record<TxState, number>>
}

export function listTransactions() {
  return request<TransactionsView>('/transactions')
}

// ------------------------------------------------------------- session --

export interface ResetResult {
  datasets: number
  proposals: number
  members: number
  events: number
  rules: number
  tables_dropped: number
  views_dropped: number
  files_removed: number
  agent_sessions_cleared: number
}

export function resetSession() {
  return request<ResetResult>('/session/reset', { method: 'POST' })
}

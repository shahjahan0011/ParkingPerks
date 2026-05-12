/**
 * types.ts — the single source of truth for API response shapes.
 *
 * TEACHING NOTE: These types mirror the Pydantic models in the FastAPI
 * backend exactly. When a field changes in the backend, TypeScript will
 * surface every place in the frontend that needs updating — at compile
 * time, not at 2am when production breaks.
 *
 * If you use `any` here, you lose that guarantee entirely. Treat `any`
 * like a fire extinguisher: it exists, but reaching for it should feel
 * wrong.
 */

export interface Qualifier {
  plate: string
  name: string
  email: string | null
  permit_number: string | null
  qualifying_days: number | null
  avg_hours: number | null
  track: 'payment' | 'permit'
}

export interface ProcessingSummary {
  date_range: string
  coverage_days: number
  read_rows: number
  total_plates: number
  payment_plates: number
  citation_plates: number
  permit_plates: number
  min_visits: number
  min_hours: number
  stage1_count: number
  stage2_payment: number
  stage2_permit: number
  stage2_total: number
  removed_citations: number
  final: number
  missing_emails: string[]
}

export interface AnalyzeResponse {
  month: string
  qualifiers: Qualifier[]
  summary: ProcessingSummary
  missing_emails: string[]
}

export interface Winner {
  plate: string
  name: string
  email: string | null
  permit_number: string | null
  track: 'payment' | 'permit'
}

export interface DrawResponse {
  month: string
  drawn_at: string
  winners: Winner[]
  pool_size: number
  is_redraw: boolean
  missing_emails: string[]
}

export interface DrawHistoryRecord {
  id: number
  month: string
  drawn_at: string
  drawn_by: string
  num_winners: number
  pool_size: number
  is_redraw: boolean
  winners: Winner[]
}

export interface MissingEmailItem {
  plate: string
  resolved: boolean
  email: string | null
}

export interface ApiError {
  detail: string
}

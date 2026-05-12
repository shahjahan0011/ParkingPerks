/**
 * client.ts — the only place in the codebase that knows how to talk to the API.
 *
 * TEACHING NOTE: This pattern is called a "service layer" or "API client."
 * Every component that needs data imports from here — never calls fetch() directly.
 *
 * Why? Three reasons:
 *  1. When we add CWL auth tokens later, we add the Authorization header in
 *     ONE place (the `request` function below), not in every component.
 *  2. Error handling is consistent. Right now errors throw. Later we might
 *     add retry logic or toast notifications — again, one place to change.
 *  3. If the API base URL changes (e.g. from /api to /v2/api), one line changes.
 *
 * This is the Open/Closed Principle: open for extension, closed for modification.
 * You extend the auth layer without modifying every component.
 */

import type {
  AnalyzeResponse,
  DrawHistoryRecord,
  DrawResponse,
  MissingEmailItem,
} from './types'

const BASE = '/api'

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }

  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Typed API surface — one function per endpoint
// ---------------------------------------------------------------------------

export const api = {
  analyze(year: number, month: number, actor: string): Promise<AnalyzeResponse> {
    return request('/analyze', {
      method: 'POST',
      body: JSON.stringify({ year, month, actor }),
    })
  },

  draw(
    year: number,
    month: number,
    actor: string,
    managerCode?: string,
  ): Promise<DrawResponse> {
    return request('/draw', {
      method: 'POST',
      body: JSON.stringify({ year, month, actor, manager_code: managerCode ?? null }),
    })
  },

  resolveEmail(month: string, plate: string, email: string, actor: string): Promise<unknown> {
    return request('/draw/resolve-email', {
      method: 'POST',
      body: JSON.stringify({ month, plate, email, actor }),
    })
  },

  getHistory(): Promise<DrawHistoryRecord[]> {
    return request('/history')
  },

  getMonthHistory(month: string): Promise<DrawHistoryRecord> {
    return request(`/history/${month}`)
  },

  getMissingEmails(month: string): Promise<MissingEmailItem[]> {
    return request(`/history/${month}/missing-emails`)
  },
}

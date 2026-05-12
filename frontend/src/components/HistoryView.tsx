/**
 * HistoryView — monthly archive of all past draws.
 *
 * TEACHING NOTE: useQuery and stale time.
 *
 * By default, TanStack Query considers data "stale" immediately after
 * it's fetched. When you switch tabs and come back, it refetches in the
 * background. For the history view, that's fine — it's cheap to fetch
 * and always current.
 *
 * If a query were expensive (like running the full qualification pipeline),
 * you'd set staleTime: 5 * 60 * 1000 to say "don't refetch for 5 minutes."
 * This is a tuning knob, not a correctness concern.
 *
 * TEACHING NOTE: Expansion pattern (accordion).
 * We store a single `expandedId` in state rather than a boolean per row.
 * This ensures only one row is expanded at a time without coordinating
 * between rows. The invariant is easy to reason about: "if expandedId
 * matches this row's id, it's open." Simple state = fewer bugs.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DrawHistoryRecord } from '../api/types'

export function HistoryView() {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const { data: records, isLoading, error } = useQuery({
    queryKey: ['draw-history'],
    queryFn: () => api.getHistory(),
  })

  return (
    <div className="view-section">
      <div className="view-header">
        <div>
          <h2>Draw History</h2>
          <p className="view-subtitle">Full archive of every draw, with winners and pool size.</p>
        </div>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <div className="alert alert-error">{(error as Error).message}</div>}

      {records && records.length === 0 && (
        <div className="alert alert-info">No draws have been run yet.</div>
      )}

      {records && records.length > 0 && (
        <div className="history-list">
          {records.map(record => (
            <HistoryRow
              key={record.id}
              record={record}
              expanded={expandedId === record.id}
              onToggle={() =>
                setExpandedId(prev => (prev === record.id ? null : record.id))
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function HistoryRow({
  record,
  expanded,
  onToggle,
}: {
  record: DrawHistoryRecord
  expanded: boolean
  onToggle: () => void
}) {
  const drawnAt = new Date(record.drawn_at).toLocaleString('en-CA', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })

  return (
    <div className="history-row">
      <button className="history-summary" onClick={onToggle}>
        <span className="history-month">{record.month}</span>
        <span className="history-meta">
          {record.num_winners} winner{record.num_winners !== 1 ? 's' : ''} from{' '}
          {record.pool_size} qualifiers
        </span>
        {record.is_redraw && <span className="badge badge-warn">Redraw</span>}
        <span className="history-date">{drawnAt}</span>
        <span className="history-chevron">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="history-detail">
          <p className="history-actor">Drawn by: {record.drawn_by}</p>
          <div className="winner-cards winner-cards--compact">
            {record.winners.map((w, i) => (
              <div key={w.plate} className="winner-card winner-card--small">
                <span className="winner-rank">#{i + 1}</span>
                <span className="mono">{w.plate}</span>
                {w.name && <span>{w.name}</span>}
                {w.email && <span className="winner-email">{w.email}</span>}
                <span className={`badge badge-${w.track}`}>{w.track}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

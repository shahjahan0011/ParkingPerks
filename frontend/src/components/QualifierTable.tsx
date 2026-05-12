/**
 * QualifierTable — shows who qualified and a processing funnel summary.
 *
 * TEACHING NOTE: useMutation vs useQuery.
 *
 * useQuery is for data that EXISTS on the server and you want to READ.
 * It auto-fetches, caches, and refetches in the background.
 *
 * useMutation is for ACTIONS — things you do to the server. Analyze is
 * an action (it triggers a pipeline and returns computed results), not
 * a stored resource, so useMutation is correct here even though it
 * returns data. The key tell: you want it to run on button click, not
 * automatically on mount.
 *
 * The `data` from useMutation is kept in component state (`result`) so
 * it persists across tab switches without refetching. If we used
 * useQuery, we'd need a cache key — that's fine too, but since analyze
 * is expensive (calls three external systems), we don't want it running
 * automatically.
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useActor } from '../context/ActorContext'
import type { AnalyzeResponse, Qualifier } from '../api/types'

interface Props {
  year: number
  month: number
  onAnalyzed: (result: AnalyzeResponse) => void
}

export function QualifierTable({ year, month, onAnalyzed }: Props) {
  const { actor } = useActor()
  const [result, setResult] = useState<AnalyzeResponse | null>(null)

  const { mutate, isPending, error } = useMutation({
    mutationFn: () => api.analyze(year, month, actor!),
    onSuccess: data => {
      setResult(data)
      onAnalyzed(data)
    },
  })

  return (
    <div className="view-section">
      <div className="view-header">
        <div>
          <h2>Qualifiers</h2>
          <p className="view-subtitle">
            Pull live data from Genetec, T2 Iris, and T2 Flex and run the
            qualification pipeline.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => mutate()}
          disabled={isPending}
        >
          {isPending ? 'Loading data…' : 'Load Qualifiers'}
        </button>
      </div>

      {error && (
        <div className="alert alert-error">
          {(error as Error).message}
        </div>
      )}

      {result && (
        <>
          <FunnelSummary summary={result.summary} />
          <QualTable qualifiers={result.qualifiers} />
        </>
      )}
    </div>
  )
}

function FunnelSummary({ summary }: { summary: AnalyzeResponse['summary'] }) {
  return (
    <div className="funnel-grid">
      <StatCard label="Plate reads" value={summary.read_rows.toLocaleString()} />
      <StatCard label="Unique plates" value={summary.total_plates.toLocaleString()} />
      <StatCard label="Passed visit threshold" value={summary.stage1_count.toLocaleString()} />
      <StatCard label="Valid payment" value={summary.stage2_payment.toLocaleString()} />
      <StatCard label="Active permits" value={summary.stage2_permit.toLocaleString()} />
      <StatCard label="Final qualifiers" value={summary.final.toLocaleString()} highlight />
    </div>
  )
}

function StatCard({
  label,
  value,
  highlight = false,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <div className={`stat-card ${highlight ? 'stat-card--highlight' : ''}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

function QualTable({ qualifiers }: { qualifiers: Qualifier[] }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Plate</th>
            <th>Name</th>
            <th>Email</th>
            <th>Permit No.</th>
            <th>Days</th>
            <th>Avg Stay</th>
            <th>Track</th>
          </tr>
        </thead>
        <tbody>
          {qualifiers.map((q, i) => (
            <tr key={q.plate} className={q.track === 'permit' ? 'row-permit' : ''}>
              <td className="text-center">{i + 1}</td>
              <td className="mono">{q.plate}</td>
              <td>{q.name || '—'}</td>
              <td>{q.email ?? <span className="badge badge-warn">Missing</span>}</td>
              <td>{q.permit_number ?? '—'}</td>
              <td className="text-center">{q.qualifying_days ?? 'N/A'}</td>
              <td className="text-center">
                {q.avg_hours != null ? `${q.avg_hours}h` : 'N/A'}
              </td>
              <td>
                <span className={`badge badge-${q.track}`}>
                  {q.track}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

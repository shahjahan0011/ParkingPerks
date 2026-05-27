/**
 * QualifierTable — data sources + qualifier pipeline.
 *
 * Data source layout:
 *  Card A — Plate Reads: staff uploads the month's .xlsx from Genetec.
 *  Card B — Auto-fetched: Payments (T2 Iris stub), Citations & Permits (T2 Flex API).
 *
 * Two mutations:
 *  uploadMutation  → POST /api/upload/reads  (stores file server-side)
 *  analyzeMutation → POST /api/analyze       (runs the full pipeline)
 *
 * The upload is optional — if no file has been uploaded the Genetec client
 * falls back to test-data. "Load Qualifiers" is always available.
 */

import { useRef, useState } from 'react'
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
  const [uploadedName, setUploadedName] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── upload mutation ───────────────────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadReads(file),
    onSuccess: (data) => setUploadedName(data.filename),
  })

  function handleFile(file: File | undefined) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      alert('Please select an .xlsx spreadsheet.')
      return
    }
    uploadMutation.mutate(file)
  }

  // ── analyze mutation ──────────────────────────────────────────────────────
  const analyzeMutation = useMutation({
    mutationFn: () => api.analyze(year, month, actor!),
    onSuccess: (data) => {
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
            Load data from all sources, then run the qualification pipeline.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => analyzeMutation.mutate()}
          disabled={analyzeMutation.isPending}
        >
          {analyzeMutation.isPending ? 'Loading data…' : 'Load Qualifiers'}
        </button>
      </div>

      {/* ── Data source cards ────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>

        {/* Card A — Plate Reads (manual upload) */}
        <div className="card">
          <div className="card-header">
            <div className="card-step">1</div>
            <span className="card-title">
              Plate Reads
              <span className="card-title-note"> — Genetec export (.xlsx)</span>
            </span>
          </div>
          <div className="card-body">
            <div
              className={
                'upload-zone' +
                (isDragOver ? ' dragover' : '') +
                (uploadedName ? ' loaded' : '')
              }
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDragOver(false)
                handleFile(e.dataTransfer.files[0])
              }}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                style={{ display: 'none' }}
                onChange={(e) => handleFile(e.target.files?.[0])}
              />
              <div className="upload-icon">
                {uploadMutation.isPending ? '⏳' : uploadedName ? '✅' : '📈'}
              </div>
              <div className="upload-zone-title">
                {uploadedName ? 'Plate reads loaded' : 'Drop plate reads here'}
              </div>
              <div className="upload-zone-ext">.xlsx</div>
              <div className="upload-hint">
                {uploadMutation.isPending
                  ? 'Uploading…'
                  : uploadedName
                    ? uploadedName
                    : 'click or drag • header on row 2'}
              </div>
            </div>
            {uploadMutation.isError && (
              <p style={{ color: 'var(--red)', fontSize: '12px', marginTop: '8px' }}>
                {(uploadMutation.error as Error).message}
              </p>
            )}
          </div>
        </div>

        {/* Card B — Auto-fetched sources */}
        <div className="card">
          <div className="card-header">
            <div className="card-step auto">✓</div>
            <span className="card-title">Auto-fetched Sources</span>
          </div>
          <div className="card-body">
            <div className="auto-sources">
              <div className="auto-source-row">
                <span className="auto-source-icon">💳</span>
                <div>
                  <div className="auto-source-label">Payments</div>
                  <div className="auto-source-sub">T2 Iris • test-data stub</div>
                </div>
              </div>
              <div className="auto-source-row">
                <span className="auto-source-icon">🚨</span>
                <div>
                  <div className="auto-source-label">Citations</div>
                  <div className="auto-source-sub">T2 Flex API</div>
                </div>
              </div>
              <div className="auto-source-row">
                <span className="auto-source-icon">🅿️</span>
                <div>
                  <div className="auto-source-label">Permit Holders</div>
                  <div className="auto-source-sub">T2 Flex API</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Errors ──────────────────────────────────────────────────────── */}
      {analyzeMutation.isError && (
        <div className="alert alert-error">
          {(analyzeMutation.error as Error).message}
        </div>
      )}

      {/* ── Results ─────────────────────────────────────────────────────── */}
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
    <div className="funnel-grid" style={{ marginBottom: '24px' }}>
      <StatCard label="Plate reads"            value={summary.read_rows.toLocaleString()} />
      <StatCard label="Unique plates"           value={summary.total_plates.toLocaleString()} />
      <StatCard label="Passed visit threshold"  value={summary.stage1_count.toLocaleString()} />
      <StatCard label="Valid payment"           value={summary.stage2_payment.toLocaleString()} />
      <StatCard label="Active permits"          value={summary.stage2_permit.toLocaleString()} />
      <StatCard label="Final qualifiers"        value={summary.final.toLocaleString()} highlight />
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
    <div className={'stat-card' + (highlight ? ' stat-card--highlight' : '')}>
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
              <td>
                {q.email
                  ? q.email
                  : <span className="badge badge-warn">Missing</span>
                }
              </td>
              <td>{q.permit_number ?? '—'}</td>
              <td className="text-center">{q.qualifying_days ?? 'N/A'}</td>
              <td className="text-center">
                {q.avg_hours != null ? `${q.avg_hours}h` : 'N/A'}
              </td>
              <td>
                <span className={'badge badge-' + q.track}>
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

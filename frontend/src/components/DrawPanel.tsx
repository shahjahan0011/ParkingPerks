/**
 * DrawPanel — runs the draw and shows winners.
 *
 * TEACHING NOTE: Optimistic UI vs. pessimistic UI.
 *
 * We use pessimistic UI here: the button is disabled while the mutation
 * is in flight, and the result is shown only after the server confirms.
 * This is correct for a draw — you never want the UI to show a winner
 * before the database has committed it. If the network fails mid-draw,
 * the state stays consistent.
 *
 * Optimistic UI (show the result before the server confirms, roll back
 * on error) is appropriate for low-stakes actions like "like a post."
 * Never use it for anything involving money, fairness, or audits.
 *
 * MANAGER CODE flow: if the server returns 403 with the message about
 * redraws, we prompt for the manager code inline rather than routing
 * to a separate page. Keeping the confirmation context-adjacent (right
 * next to the button that triggered it) reduces cognitive load.
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useActor } from '../context/ActorContext'
import type { DrawResponse } from '../api/types'

interface Props {
  year: number
  month: number
  poolSize: number
}

export function DrawPanel({ year, month, poolSize }: Props) {
  const { actor } = useActor()
  const [result, setResult] = useState<DrawResponse | null>(null)
  const [needsManagerCode, setNeedsManagerCode] = useState(false)
  const [managerCode, setManagerCode] = useState('')

  const { mutate, isPending, error } = useMutation({
    mutationFn: (code?: string) => api.draw(year, month, actor!, code),
    onSuccess: data => {
      setResult(data)
      setNeedsManagerCode(false)
      setManagerCode('')
    },
    onError: (err: Error) => {
      if (err.message.toLowerCase().includes('manager code')) {
        setNeedsManagerCode(true)
      }
    },
  })

  const monthLabel = `${year}-${String(month).padStart(2, '0')}`

  return (
    <div className="view-section">
      <div className="view-header">
        <div>
          <h2>Draw</h2>
          <p className="view-subtitle">
            Run a cryptographically secure draw for <strong>{monthLabel}</strong>.
            {poolSize > 0 && ` Pool size: ${poolSize} qualifiers.`}
          </p>
        </div>
      </div>

      {poolSize === 0 && !result && (
        <div className="alert alert-info">
          Load qualifiers first before running the draw.
        </div>
      )}

      {error && !needsManagerCode && (
        <div className="alert alert-error">{(error as Error).message}</div>
      )}

      {needsManagerCode && (
        <div className="manager-code-prompt">
          <p>
            <strong>This month has already been drawn.</strong> Enter the manager
            code to authorise a redraw. Every redraw is permanently logged.
          </p>
          <div className="manager-code-row">
            <input
              type="password"
              placeholder="Manager code"
              value={managerCode}
              onChange={e => setManagerCode(e.target.value)}
            />
            <button
              className="btn-danger"
              disabled={!managerCode || isPending}
              onClick={() => mutate(managerCode)}
            >
              Authorise Redraw
            </button>
          </div>
        </div>
      )}

      {!needsManagerCode && poolSize > 0 && !result && (
        <button
          className="btn-primary btn-draw"
          onClick={() => mutate(undefined)}
          disabled={isPending}
        >
          {isPending ? 'Drawing…' : `Run Draw for ${monthLabel}`}
        </button>
      )}

      {result && (
        <div className="draw-result">
          {result.is_redraw && (
            <div className="alert alert-warn">
              This is a manager-authorised redraw. Previous draw was overwritten.
            </div>
          )}
          <h3>
            {result.winners.length === 1 ? '🏆 Winner' : `🏆 Winners (${result.winners.length})`}
          </h3>
          <div className="winner-cards">
            {result.winners.map(w => (
              <div key={w.plate} className="winner-card">
                <div className="winner-plate mono">{w.plate}</div>
                {w.name && <div className="winner-name">{w.name}</div>}
                {w.email
                  ? <div className="winner-email">{w.email}</div>
                  : <div className="badge badge-warn">No email — see Missing Emails tab</div>
                }
                <span className={`badge badge-${w.track}`}>{w.track} track</span>
              </div>
            ))}
          </div>
          {result.missing_emails.length > 0 && (
            <div className="alert alert-warn" style={{ marginTop: '1rem' }}>
              {result.missing_emails.length} winner(s) have no email address on file.
              Switch to the <strong>Missing Emails</strong> tab to resolve before
              notifications are sent.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * MissingEmailQueue — manager resolves missing emails for payment-track winners.
 *
 * TEACHING NOTE: Controlled vs uncontrolled inputs.
 *
 * A "controlled" input is one where React owns the value:
 *   <input value={state} onChange={e => setState(e.target.value)} />
 * An "uncontrolled" input lets the DOM own it (uses ref to read it).
 *
 * Always use controlled inputs in React. Uncontrolled inputs make it
 * hard to validate, hard to reset, and create subtle bugs when the
 * component re-renders. The only exception: file inputs (React can't
 * set their value for security reasons).
 *
 * The `emailInputs` state here is a Map from plate → typed email value,
 * keyed by plate. This lets each row have its own independent input
 * without a component per row. It's a common pattern for "list of editable
 * items" that avoids creating a component just to hold one field's state.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useActor } from '../context/ActorContext'

interface Props {
  month: string
}

export function MissingEmailQueue({ month }: Props) {
  const { actor } = useActor()
  const queryClient = useQueryClient()
  const [emailInputs, setEmailInputs] = useState<Record<string, string>>({})

  const { data: items, isLoading, error } = useQuery({
    queryKey: ['missing-emails', month],
    queryFn: () => api.getMissingEmails(month),
    enabled: !!month,
  })

  const { mutate: resolve, isPending } = useMutation({
    mutationFn: ({ plate, email }: { plate: string; email: string }) =>
      api.resolveEmail(month, plate, email, actor!),
    onSuccess: () => {
      // Invalidate the query so the list refreshes automatically.
      // TEACHING NOTE: This is the correct TanStack Query pattern for
      // "after I change something, re-fetch the affected data."
      // Don't update the cache manually — let the server be the source
      // of truth and re-fetch. Only do manual cache updates if the
      // re-fetch would be too slow or too expensive.
      queryClient.invalidateQueries({ queryKey: ['missing-emails', month] })
    },
  })

  if (!month) {
    return (
      <div className="view-section">
        <div className="alert alert-info">Run a draw first to see missing emails.</div>
      </div>
    )
  }

  return (
    <div className="view-section">
      <div className="view-header">
        <div>
          <h2>Missing Emails</h2>
          <p className="view-subtitle">
            Payment-track winners with no email on file. Enter each email manually
            so winner notifications can be sent.
          </p>
        </div>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <div className="alert alert-error">{(error as Error).message}</div>}

      {items && items.length === 0 && (
        <div className="alert alert-success">
          All winners have email addresses — notifications have been sent automatically.
        </div>
      )}

      {items && items.length > 0 && (
        <div className="missing-email-list">
          {items.map(item => (
            <div key={item.plate} className={`missing-email-row ${item.resolved ? 'resolved' : ''}`}>
              <div className="mono missing-plate">{item.plate}</div>
              {item.resolved ? (
                <div className="resolved-email">
                  ✓ {item.email}
                </div>
              ) : (
                <div className="resolve-form">
                  <input
                    type="email"
                    placeholder="winner@ubc.ca"
                    value={emailInputs[item.plate] ?? ''}
                    onChange={e =>
                      setEmailInputs(prev => ({ ...prev, [item.plate]: e.target.value }))
                    }
                  />
                  <button
                    className="btn-primary"
                    disabled={!emailInputs[item.plate] || isPending}
                    onClick={() =>
                      resolve({ plate: item.plate, email: emailInputs[item.plate] })
                    }
                  >
                    Save & Notify
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

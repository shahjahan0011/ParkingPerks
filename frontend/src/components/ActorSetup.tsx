/**
 * ActorSetup — a blocking modal shown on first load if no actor is set.
 *
 * TEACHING NOTE: This is a "gate" component. The parent (App.tsx) checks
 * if actor === null and renders this instead of the dashboard. It's not
 * a traditional modal — it's a conditional render. This is simpler and
 * more predictable than a portal-based modal with an open/close state.
 *
 * The email format validation uses HTML5's built-in `type="email"` —
 * not a regex. Regex email validation is famously brittle. The browser's
 * built-in validator is good enough for this internal tool.
 */

import { useState, type FormEvent } from 'react'
import { useActor } from '../context/ActorContext'

export function ActorSetup() {
  const { setActor } = useActor()
  const [value, setValue] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed.includes('@')) {
      setError('Please enter your UBC email address.')
      return
    }
    setActor(trimmed)
  }

  return (
    <div className="actor-setup-overlay">
      <div className="actor-setup-card">
        <div className="actor-setup-logo">🅿️</div>
        <h1>Parking Perks Dashboard</h1>
        <p className="actor-setup-subtitle">UBC Okanagan Parking Services</p>
        <p className="actor-setup-desc">
          Enter your UBC email to identify yourself in the draw audit log.
          <br />
          <em>This is not a password — it's just your name for the record.</em>
        </p>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="you@ubc.ca"
            value={value}
            onChange={e => { setValue(e.target.value); setError('') }}
            autoFocus
            required
          />
          {error && <p className="field-error">{error}</p>}
          <button type="submit" className="btn-primary btn-full">
            Enter Dashboard
          </button>
        </form>
      </div>
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import { useActor } from '../context/ActorContext'

export function ActorSetup() {
  const { setActor } = useActor()
  const [value, setValue] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed.includes('@')) { setError('Please enter your UBC email address.'); return }
    setActor(trimmed)
  }

  return (
    <div className="actor-setup-overlay">
      <div className="actor-setup-card">
        <div className="actor-logo">🅿</div>
        <div>
          <div className="actor-ubc">UBC</div>
          <div className="actor-campus">Okanagan</div>
        </div>
        <div className="actor-title">Parking Perks Dashboard</div>
        <p className="actor-desc">
          Enter your UBC email to identify yourself in the draw audit log.
          <br /><em>This is not a password — it is just your name for the record.</em>
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
          <button type="submit" className="btn-primary btn-full">Enter Dashboard</button>
        </form>
      </div>
    </div>
  )
}

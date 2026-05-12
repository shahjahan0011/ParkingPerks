/**
 * App.tsx — the shell. Owns the month selector and tab state.
 *
 * TEACHING NOTE: State ownership.
 *
 * The current month lives here, not in individual views, because multiple
 * views need it (QualifierTable uses it to call /analyze; DrawPanel uses
 * it to call /draw; MissingEmailQueue uses it to fetch missing emails).
 * State should live in the lowest common ancestor of the components that
 * need it — here that's App.
 *
 * The `analyzeResult` also lives here so it can flow down to DrawPanel
 * as `poolSize`. We don't lift it to Context because it's not ambient
 * state — it's specific to the current session's analyze run.
 *
 * TEACHING NOTE: Tabs via state, not React Router.
 *
 * We have 4 views, all on one page. React Router adds URL routing — useful
 * when you need deep linking ("share this URL to go directly to the history
 * tab"). We don't need that here. A `activeTab` string in useState is enough
 * and zero additional dependencies.
 *
 * When you DO add routing later: replace `activeTab` with `useSearchParams`
 * or React Router's `<Routes>`. The component boundaries stay the same.
 */

import { useState } from 'react'
import { ActorSetup } from './components/ActorSetup'
import { QualifierTable } from './components/QualifierTable'
import { DrawPanel } from './components/DrawPanel'
import { MissingEmailQueue } from './components/MissingEmailQueue'
import { HistoryView } from './components/HistoryView'
import { useActor } from './context/ActorContext'
import type { AnalyzeResponse } from './api/types'

type Tab = 'qualifiers' | 'draw' | 'missing-emails' | 'history'

const TABS: { id: Tab; label: string }[] = [
  { id: 'qualifiers',    label: 'Qualifiers' },
  { id: 'draw',          label: 'Draw' },
  { id: 'missing-emails', label: 'Missing Emails' },
  { id: 'history',       label: 'History' },
]

const now = new Date()

export function App() {
  const { actor, clearActor } = useActor()
  const [activeTab, setActiveTab] = useState<Tab>('qualifiers')
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null)

  if (!actor) return <ActorSetup />

  const monthStr = `${year}-${String(month).padStart(2, '0')}`

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-brand">
          <span className="header-logo">🅿️</span>
          <div>
            <span className="header-title">Parking Perks</span>
            <span className="header-subtitle">UBC Okanagan Parking Services</span>
          </div>
        </div>

        <div className="header-controls">
          <MonthPicker year={year} month={month} onChange={(y, m) => {
            setYear(y)
            setMonth(m)
            setAnalyzeResult(null)
          }} />
          <button className="btn-ghost" onClick={clearActor} title="Switch user">
            {actor} ↩
          </button>
        </div>
      </header>

      <nav className="tab-nav">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'tab-btn--active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main className="app-main">
        {activeTab === 'qualifiers' && (
          <QualifierTable
            year={year}
            month={month}
            onAnalyzed={result => {
              setAnalyzeResult(result)
            }}
          />
        )}
        {activeTab === 'draw' && (
          <DrawPanel
            year={year}
            month={month}
            poolSize={analyzeResult?.summary.final ?? 0}
          />
        )}
        {activeTab === 'missing-emails' && (
          <MissingEmailQueue month={monthStr} />
        )}
        {activeTab === 'history' && <HistoryView />}
      </main>
    </div>
  )
}

function MonthPicker({
  year,
  month,
  onChange,
}: {
  year: number
  month: number
  onChange: (year: number, month: number) => void
}) {
  const monthNames = [
    'Jan','Feb','Mar','Apr','May','Jun',
    'Jul','Aug','Sep','Oct','Nov','Dec',
  ]

  return (
    <div className="month-picker">
      <button
        className="btn-ghost btn-icon"
        onClick={() => {
          const d = new Date(year, month - 2)
          onChange(d.getFullYear(), d.getMonth() + 1)
        }}
      >
        ‹
      </button>
      <span className="month-label">
        {monthNames[month - 1]} {year}
      </span>
      <button
        className="btn-ghost btn-icon"
        onClick={() => {
          const d = new Date(year, month)
          onChange(d.getFullYear(), d.getMonth() + 1)
        }}
      >
        ›
      </button>
    </div>
  )
}

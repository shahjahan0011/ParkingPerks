import { useState } from 'react'
import { ActorSetup }       from './components/ActorSetup'
import { QualifierTable }   from './components/QualifierTable'
import { DrawPanel }        from './components/DrawPanel'
import { MissingEmailQueue } from './components/MissingEmailQueue'
import { HistoryView }      from './components/HistoryView'
import { useActor }         from './context/ActorContext'
import type { AnalyzeResponse } from './api/types'

type Tab = 'qualifiers' | 'draw' | 'missing-emails' | 'history'

const TABS: { id: Tab; label: string }[] = [
  { id: 'qualifiers',     label: 'Qualifiers' },
  { id: 'draw',           label: 'Draw' },
  { id: 'missing-emails', label: 'Missing Emails' },
  { id: 'history',        label: 'History' },
]

const now = new Date()

export function App() {
  const { actor, clearActor } = useActor()
  const [activeTab, setActiveTab] = useState<Tab>('qualifiers')
  const [year,  setYear]  = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null)

  if (!actor) return <ActorSetup />

  const monthStr = `${year}-${String(month).padStart(2, '0')}`

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-inner">
          <div className="ubc-wordmark">
            <span className="ubc-text">UBC</span>
            <span className="ubc-campus">Okanagan</span>
          </div>
          <div className="dept-block">
            <span className="dept-name">Parking Services</span>
            <span className="dept-sub">Parking Perks — Monthly Draw</span>
          </div>
          <div className="header-controls">
            <MonthPicker year={year} month={month} onChange={(y, m) => {
              setYear(y); setMonth(m); setAnalyzeResult(null)
            }} />
            <button className="btn-ghost" onClick={clearActor} title="Switch user">
              {actor} ↩
            </button>
          </div>
        </div>
      </header>

      {/* ── Tab nav ── */}
      <nav className="tab-nav">
        <div className="tab-nav-inner">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? 'tab-btn--active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      {/* ── Content ── */}
      <div className="main-wrap">
        <main className="app-main">
          {activeTab === 'qualifiers' && (
            <QualifierTable
              year={year} month={month}
              onAnalyzed={result => setAnalyzeResult(result)}
            />
          )}
          {activeTab === 'draw' && (
            <DrawPanel
              year={year} month={month}
              poolSize={analyzeResult?.summary.final ?? 0}
            />
          )}
          {activeTab === 'missing-emails' && <MissingEmailQueue month={monthStr} />}
          {activeTab === 'history'        && <HistoryView />}
        </main>
      </div>
    </div>
  )
}

function MonthPicker({
  year, month, onChange,
}: {
  year: number
  month: number
  onChange: (year: number, month: number) => void
}) {
  const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return (
    <div className="month-picker">
      <button className="btn-ghost btn-icon" onClick={() => {
        const d = new Date(year, month - 2); onChange(d.getFullYear(), d.getMonth() + 1)
      }}>‹</button>
      <span className="month-label">{names[month - 1]} {year}</span>
      <button className="btn-ghost btn-icon" onClick={() => {
        const d = new Date(year, month); onChange(d.getFullYear(), d.getMonth() + 1)
      }}>›</button>
    </div>
  )
}

import { useState } from 'react'
import Home from './components/Home/Home'
import './App.css'

export default function App() {
  const [page, setPage] = useState<'home' | 'intelligence'>('home')

  return (
    <main className="vantex-app">
      {page === 'home' ? (
        <Home onOpenIntelligence={() => setPage('intelligence')} />
      ) : (
        <section className="intelligence-page">
          <header className="intelligence-header">
            <button className="back-button" onClick={() => setPage('home')}>
              ← Back to VANTEX
            </button>
            <span className="system-badge">
              <span className="status-dot" />
              LOCAL INTELLIGENCE
            </span>
          </header>

          <div className="intelligence-content">
            <span className="eyebrow">SYSTEM MONITOR</span>
            <h1>PC Intelligence</h1>
            <p className="intelligence-description">
              Monitor your PC, investigate system issues, and review
              recommended fixes from one place.
            </p>

            <div className="intelligence-grid">
              <article className="intelligence-card">
                <span>01 / PERFORMANCE</span>
                <h2>System Health</h2>
                <p>CPU, memory and disk monitoring will appear here.</p>
                <span className="feature-status">ENGINE NOT CONNECTED</span>
              </article>

              <article className="intelligence-card">
                <span>02 / DIAGNOSTICS</span>
                <h2>Issue Detection</h2>
                <p>Detected problems and diagnostic results will appear here.</p>
                <span className="feature-status">ENGINE NOT CONNECTED</span>
              </article>

              <article className="intelligence-card">
                <span>03 / REMEDIATION</span>
                <h2>Safe Fixes</h2>
                <p>Review proposed changes before approving system fixes.</p>
                <span className="feature-status">ENGINE NOT CONNECTED</span>
              </article>
            </div>

            <p className="intelligence-note">
              Monitoring and repair engines are not implemented yet.
              No system changes are being made.
            </p>
          </div>
        </section>
      )}
    </main>
  )
}
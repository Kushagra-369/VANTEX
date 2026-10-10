import { useEffect, useState } from 'react'
import Home from './components/Home/Home'
import './App.css'

type SystemMetrics = {
  cpu_percent: number
  ram_percent: number
  ram_total_gb: number
  ram_available_gb: number
  disk_percent: number
  disk_free_gb: number
}

type SystemStatus = {
  agent: string
  connected: boolean
  timestamp: string
  system: SystemMetrics
}

function PCIntelligence({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<SystemStatus | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState('')

  useEffect(() => {
    let active = true

    const fetchMetrics = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/agent/system')
        if (!response.ok) throw new Error('Could not fetch system metrics')

        const result: SystemStatus = await response.json()
        if (!active) return

        setData(result)
        setError('')
        setLastUpdated(new Date().toLocaleTimeString())
      } catch {
        if (active) setError('Local agent is unavailable. Check whether the VANTEX backend is running.')
      } finally {
        if (active) setLoading(false)
      }
    }

    void fetchMetrics()
    const interval = window.setInterval(() => void fetchMetrics(), 3000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  const metrics = data?.system

  const metricCards = metrics
    ? [
        {
          name: 'CPU Usage',
          value: metrics.cpu_percent,
          detail: 'Current processor utilization',
        },
        {
          name: 'Memory Usage',
          value: metrics.ram_percent,
          detail: `${metrics.ram_available_gb.toFixed(2)} GB RAM available of ${metrics.ram_total_gb.toFixed(2)} GB`,
        },
        {
          name: 'Disk Usage',
          value: metrics.disk_percent,
          detail: `${metrics.disk_free_gb.toFixed(2)} GB disk space free`,
        },
      ]
    : []

  return (
    <section className="intelligence-page">
      <header className="intelligence-header">
        <button className="back-button" onClick={onBack}>
          ← Back to VANTEX
        </button>
        <span className="system-badge">
          <span className={`status-dot ${error ? 'offline' : 'online'}`} />
          {error ? 'AGENT OFFLINE' : 'LOCAL INTELLIGENCE'}
        </span>
      </header>

      <div className="intelligence-content">
        <span className="eyebrow">SYSTEM MONITOR</span>
        <h1>PC Intelligence</h1>
        <p className="intelligence-description">
          Live system metrics from your local VANTEX agent.
        </p>

        <div className="intelligence-connection">
          <span className={`status-dot ${error ? 'offline' : 'online'}`} />
          <span>
            {loading
              ? 'Connecting to local agent...'
              : error
                ? error
                : `${data?.agent ?? 'VANTEX Local Agent'} · Connected`}
          </span>
          {lastUpdated && !error && (
            <span className="metrics-updated">Updated {lastUpdated}</span>
          )}
        </div>

        {error && (
          <div className="intelligence-error" role="alert">
            {error}
          </div>
        )}

        <div className="intelligence-grid">
          {metricCards.map((metric) => (
            <article className="intelligence-card" key={metric.name}>
              <span>LIVE / PERFORMANCE</span>
              <h2>{metric.name}</h2>

              <div className="metric-value">
                {metric.value.toFixed(1)}
                <span>%</span>
              </div>

              <div
                className="metric-track"
                role="progressbar"
                aria-label={metric.name}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.min(100, Math.max(0, metric.value))}
              >
                <div
                  className="metric-fill"
                  style={{
                    width: `${Math.min(100, Math.max(0, metric.value))}%`,
                  }}
                />
              </div>

              <p>{metric.detail}</p>
              <span className="feature-status">
                {metric.value >= 90 ? 'HIGH UTILIZATION' : 'MONITORING'}
              </span>
            </article>
          ))}

          <article className="intelligence-card">
            <span>04 / AGENT STATUS</span>
            <h2>Local Agent</h2>
            <div className="agent-status-value">
              <span className={`status-dot ${error ? 'offline' : 'online'}`} />
              {error ? 'Disconnected' : loading ? 'Connecting...' : 'Connected'}
            </div>
            <p>Metrics refresh automatically every 3 seconds.</p>
            <span className="feature-status">
              {error ? 'CHECK BACKEND' : 'LIVE CONNECTION'}
            </span>
          </article>
        </div>

        <p className="intelligence-note">
          Monitoring only. VANTEX is not changing system settings or terminating processes.
        </p>
      </div>
    </section>
  )
}

export default function App() {
  const [page, setPage] = useState<'home' | 'intelligence'>('home')

  return (
    <main className="vantex-app">
      {page === 'home' ? (
        <Home onOpenIntelligence={() => setPage('intelligence')} />
      ) : (
        <PCIntelligence onBack={() => setPage('home')} />
      )}
    </main>
  )
}
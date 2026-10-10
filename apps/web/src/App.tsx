
import { useCallback, useEffect, useState } from 'react'
import Home from './components/Home/Home'
import './App.css'

type HealthStatus = 'up' | 'down' | 'running' | 'checking' | 'unknown'

type SystemMetrics = {
  cpu_percent: number
  ram_percent: number
  disk_percent: number
  ram_total_gb?: number
  ram_available_gb?: number
  disk_free_gb?: number
}

type WebsiteStatus = {
  name: string
  url: string
  status: HealthStatus
}

type ApplicationStatus = {
  name: string
  status: HealthStatus
}

type MonitorStatus = {
  updated_at: string
  monitor: string
  system: SystemMetrics
  websites: WebsiteStatus[]
  applications: ApplicationStatus[]
  active_incidents: string[]
}

type ExtraSystemData = {
  agent?: string
  connected?: boolean
  timestamp?: string
  system?: Partial<SystemMetrics>
}

type SectionKey = 'overview' | 'processes' | 'network' | 'incidents'

function formatTime(value?: string) {
  if (!value) return 'Not available'

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function StatusPill({ status }: { status: string }) {
  const good = ['up', 'running', 'connected', 'healthy'].includes(
    status.toLowerCase(),
  )
  const pending = ['checking', 'unknown'].includes(status.toLowerCase())

  return (
    <span
      className={`monitor-status ${good ? 'online' : pending ? 'checking' : 'offline'}`}
    >
      {status.toUpperCase()}
    </span>
  )
}

function MetricCard({
  name,
  value,
  detail,
  unit = '%',
}: {
  name: string
  value?: number
  detail: string
  unit?: string
}) {
  const available = typeof value === 'number' && Number.isFinite(value)
  const safeValue = available ? Math.min(100, Math.max(0, value)) : 0

  return (
    <article className="intelligence-card">
      <span>LIVE / PERFORMANCE</span>
      <h2>{name}</h2>

      <div className="metric-value">
        {available ? value.toFixed(1) : '—'}
        {available && <span>{unit}</span>}
      </div>

      <div
        className="metric-track"
        role="progressbar"
        aria-label={name}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={available ? safeValue : 0}
      >
        <div
          className="metric-fill"
          style={{ width: `${available ? safeValue : 0}%` }}
        />
      </div>

      <p>{available ? detail : 'This metric is not available from the agent yet.'}</p>
      <span className="feature-status">
        {available ? (safeValue >= 90 ? 'HIGH UTILIZATION' : 'MONITORING') : 'NOT AVAILABLE'}
      </span>
    </article>
  )
}

function PCIntelligence({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<MonitorStatus | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState('')
  const [section, setSection] = useState<SectionKey>('overview')

  const fetchStatus = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch(
      'http://127.0.0.1:8000/api/agent/monitor/status',
      { cache: 'no-store', signal },
    )

    if (!response.ok) {
      throw new Error(`Monitor API returned HTTP ${response.status}`)
    }

    const status: MonitorStatus = await response.json()

    // Enrich the snapshot with extra fields if the existing system API provides them.
    let enriched = status
    try {
      const extraResponse = await fetch(
        'http://127.0.0.1:8000/api/agent/system',
        { cache: 'no-store', signal },
      )

      if (extraResponse.ok) {
        const extra: ExtraSystemData = await extraResponse.json()
        if (extra.system) {
          enriched = {
            ...status,
            system: { ...status.system, ...extra.system },
          }
        }
      }
    } catch {
      // The monitor snapshot remains usable if optional enrichment fails.
    }

    setData(enriched)
    setError('')
    setLastUpdated(new Date().toLocaleTimeString())
  }, [])

  useEffect(() => {
    let active = true
    let controller: AbortController | null = null

    const refresh = async () => {
      controller?.abort()
      controller = new AbortController()

      try {
        await fetchStatus(controller.signal)
      } catch (err) {
        if (!active || (err instanceof Error && err.name === 'AbortError')) return
        setError(
          'Cannot reach the VANTEX monitor API. Check the backend and background service.',
        )
      } finally {
        if (active) setLoading(false)
      }
    }

    void refresh()
    const interval = window.setInterval(() => void refresh(), 3000)

    return () => {
      active = false
      window.clearInterval(interval)
      controller?.abort()
    }
  }, [fetchStatus])

  const metrics = data?.system
  const incidents = data?.active_incidents ?? []
  const websites = data?.websites ?? []
  const applications = data?.applications ?? []

  const navigation: { key: SectionKey; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'processes', label: 'Processes' },
    { key: 'network', label: 'Network' },
    { key: 'incidents', label: `Incidents${incidents.length ? ` (${incidents.length})` : ''}` },
  ]

  return (
    <section className="intelligence-page">
      <header className="intelligence-header">
        <button className="back-button" onClick={onBack}>
          ← Back to VANTEX
        </button>
        <span className="system-badge">
          <span className={`status-dot ${error ? 'offline' : data ? 'online' : ''}`} />
          {error ? 'MONITOR OFFLINE' : 'PC OPERATIONS CENTER'}
        </span>
      </header>

      <div className="intelligence-content">
        <span className="eyebrow">VANTEX / LOCAL TELEMETRY</span>
        <h1>PC Intelligence</h1>
        <p className="intelligence-description">
          Your system health, service availability, process checks and incidents in one place.
        </p>

        <div className="intelligence-connection">
          <span className={`status-dot ${error ? 'offline' : data ? 'online' : ''}`} />
          <span>
            {loading
              ? 'Connecting to local monitor...'
              : error
                ? error
                : 'Background monitor connected'}
          </span>
          <span className="metrics-updated">
            Refreshed {lastUpdated || '—'}
          </span>
        </div>

        {error && (
          <div className="intelligence-error" role="alert">
            {error}
          </div>
        )}

        <nav className="pc-intel-nav" aria-label="PC Intelligence sections">
          {navigation.map((item) => (
            <button
              key={item.key}
              className={`pc-intel-tab ${section === item.key ? 'active' : ''}`}
              onClick={() => setSection(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {section === 'overview' && (
          <>
            <section className="intel-block">
              <div className="monitor-section-heading">
                <span className="eyebrow">01 / SYSTEM HEALTH</span>
                <h2>Performance Overview</h2>
              </div>

              <div className="intelligence-grid">
                <MetricCard
                  name="CPU Usage"
                  value={metrics?.cpu_percent}
                  detail="Current processor utilization"
                />
                <MetricCard
                  name="Memory Usage"
                  value={metrics?.ram_percent}
                  detail={
                    metrics?.ram_available_gb !== undefined &&
                    metrics?.ram_total_gb !== undefined
                      ? `${metrics.ram_available_gb.toFixed(2)} GB available of ${metrics.ram_total_gb.toFixed(2)} GB`
                      : 'Current system memory utilization'
                  }
                />
                <MetricCard
                  name="Disk Usage"
                  value={metrics?.disk_percent}
                  detail={
                    metrics?.disk_free_gb !== undefined
                      ? `${metrics.disk_free_gb.toFixed(2)} GB free`
                      : 'Root filesystem utilization'
                  }
                />
                <article className="intelligence-card">
                  <span>04 / MONITOR SERVICE</span>
                  <h2>Background Engine</h2>
                  <div className="agent-status-value">
                    <span className={`status-dot ${error ? 'offline' : data ? 'online' : ''}`} />
                    {error ? 'Unavailable' : data?.monitor === 'running' ? 'Running' : 'Checking'}
                  </div>
                  <p>Checks run independently of this page.</p>
                  <span className="feature-status">
                    {data?.monitor === 'running' ? 'SERVICE REPORTS RUNNING' : 'STATUS UNKNOWN'}
                  </span>
                </article>
              </div>
            </section>

            <section className="monitor-section">
              <div className="monitor-section-heading">
                <span className="eyebrow">02 / WEBSITE HEALTH</span>
                <h2>Configured Websites</h2>
              </div>
              <div className="monitor-list">
                {websites.map((site) => (
                  <article className="monitor-row" key={site.name}>
                    <div className="monitor-row-main">
                      <span className={`status-dot ${site.status === 'up' ? 'online' : 'offline'}`} />
                      <div>
                        <h3>{site.name}</h3>
                        <p>{site.url}</p>
                      </div>
                    </div>
                    <StatusPill status={site.status} />
                  </article>
                ))}
                {websites.length === 0 && (
                  <p className="intelligence-note">No websites configured.</p>
                )}
              </div>
            </section>

            <section className="monitor-section">
              <div className="monitor-section-heading">
                <span className="eyebrow">03 / APPLICATION HEALTH</span>
                <h2>Configured Applications</h2>
              </div>
              <div className="monitor-list">
                {applications.map((app) => (
                  <article className="monitor-row" key={app.name}>
                    <div className="monitor-row-main">
                      <span className={`status-dot ${app.status === 'running' ? 'online' : 'offline'}`} />
                      <div>
                        <h3>{app.name}</h3>
                        <p>Configured process monitor</p>
                      </div>
                    </div>
                    <StatusPill status={app.status} />
                  </article>
                ))}
                {applications.length === 0 && (
                  <p className="intelligence-note">No applications configured.</p>
                )}
              </div>
            </section>

            <section className="monitor-section">
              <div className="monitor-section-heading">
                <span className="eyebrow">04 / INCIDENT RESPONSE</span>
                <h2>Active Incidents</h2>
              </div>
              <div className="monitor-list">
                {incidents.length ? incidents.map((incident) => (
                  <article className="monitor-row" key={incident}>
                    <div className="monitor-row-main">
                      <span className="status-dot offline" />
                      <div>
                        <h3>{incident}</h3>
                        <p>Active issue detected by the background monitor</p>
                      </div>
                    </div>
                    <StatusPill status="active" />
                  </article>
                )) : (
                  <article className="monitor-row">
                    <div className="monitor-row-main">
                      <span className="status-dot online" />
                      <div>
                        <h3>No active incidents</h3>
                        <p>All currently configured checks are healthy.</p>
                      </div>
                    </div>
                    <StatusPill status="healthy" />
                  </article>
                )}
              </div>
            </section>
          </>
        )}

        {section === 'processes' && (
          <section className="monitor-section">
            <div className="monitor-section-heading">
              <span className="eyebrow">PROCESS INTELLIGENCE</span>
              <h2>Application Processes</h2>
            </div>
            <div className="monitor-list">
              {applications.map((app) => (
                <article className="monitor-row" key={app.name}>
                  <div className="monitor-row-main">
                    <span className={`status-dot ${app.status === 'running' ? 'online' : 'offline'}`} />
                    <div>
                      <h3>{app.name}</h3>
                      <p>Configured process pattern; detailed PID and resource usage are not exposed yet.</p>
                    </div>
                  </div>
                  <StatusPill status={app.status} />
                </article>
              ))}
              <article className="monitor-row">
                <div className="monitor-row-main">
                  <span className="status-dot" />
                  <div>
                    <h3>Top CPU / RAM processes</h3>
                    <p>Requires a process telemetry endpoint in the local agent.</p>
                  </div>
                </div>
                <StatusPill status="not available" />
              </article>
            </div>
          </section>
        )}

        {section === 'network' && (
          <section className="monitor-section">
            <div className="monitor-section-heading">
              <span className="eyebrow">NETWORK INTELLIGENCE</span>
              <h2>Connectivity</h2>
            </div>
            <div className="monitor-list">
              {websites.map((site) => (
                <article className="monitor-row" key={site.name}>
                  <div className="monitor-row-main">
                    <span className={`status-dot ${site.status === 'up' ? 'online' : 'offline'}`} />
                    <div>
                      <h3>{site.name}</h3>
                      <p>{site.url}</p>
                    </div>
                  </div>
                  <StatusPill status={site.status} />
                </article>
              ))}
              <article className="monitor-row">
                <div className="monitor-row-main">
                  <span className="status-dot" />
                  <div>
                    <h3>Latency, bandwidth and packet loss</h3>
                    <p>These measurements require additional network monitoring logic.</p>
                  </div>
                </div>
                <StatusPill status="not available" />
              </article>
            </div>
          </section>
        )}

        {section === 'incidents' && (
          <section className="monitor-section">
            <div className="monitor-section-heading">
              <span className="eyebrow">INCIDENT RESPONSE</span>
              <h2>Active Issues</h2>
            </div>
            <div className="monitor-list">
              {incidents.length ? incidents.map((incident) => (
                <article className="monitor-row" key={incident}>
                  <div className="monitor-row-main">
                    <span className="status-dot offline" />
                    <div>
                      <h3>{incident}</h3>
                      <p>Currently reported as active.</p>
                    </div>
                  </div>
                  <StatusPill status="active" />
                </article>
              )) : (
                <article className="monitor-row">
                  <div className="monitor-row-main">
                    <span className="status-dot online" />
                    <div>
                      <h3>No active incidents</h3>
                      <p>No current failures are reported by the monitor.</p>
                    </div>
                  </div>
                  <StatusPill status="healthy" />
                </article>
              )}
            </div>
            <p className="intelligence-note">
              This view shows active incidents only. Historical incidents need persistent event storage, which has not been implemented yet.
            </p>
          </section>
        )}

        <section className="monitor-section">
          <div className="monitor-section-heading">
            <span className="eyebrow">SYSTEM DETAILS</span>
            <h2>Agent Snapshot</h2>
          </div>
          <div className="monitor-list">
            <article className="monitor-row">
              <div className="monitor-row-main">
                <div>
                  <h3>Snapshot timestamp</h3>
                  <p>{formatTime(data?.updated_at)}</p>
                </div>
              </div>
            </article>
            <article className="monitor-row">
              <div className="monitor-row-main">
                <div>
                  <h3>Configured websites</h3>
                  <p>{websites.length} target(s)</p>
                </div>
              </div>
            </article>
            <article className="monitor-row">
              <div className="monitor-row-main">
                <div>
                  <h3>Configured applications</h3>
                  <p>{applications.length} target(s)</p>
                </div>
              </div>
            </article>
          </div>
        </section>

        <p className="intelligence-note">
          Actual metrics only. Hardware temperature, battery, detailed processes, network throughput, disk I/O and historical incident timelines are not exposed by the current monitor yet. No automatic repairs are performed.
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

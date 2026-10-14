import { useCallback, useEffect, useState } from 'react';
import Home from './components/Home/Home';
import './App.css';

type HealthStatus = 'up' | 'down' | 'running' | 'checking' | 'unknown';

type SystemMetrics = {
  cpu_percent: number;
  ram_percent: number;
  disk_percent: number;
  [key: string]: unknown;
};

type MonitorData = {
  metrics?: Partial<SystemMetrics>;
  system?: Partial<SystemMetrics>;
  processes?: unknown[];
  network?: unknown;
  incidents?: unknown[];
  engine?: unknown;
  websites?: unknown[];
  applications?: unknown[];
  [key: string]: unknown;
};

type PCIntelligenceProps = {
  onBack: () => void;
};

const API = 'http://127.0.0.1:8000';

async function fetchJSON<T,>(url: string): Promise<T> {
  const response = await fetch(url);
  const body: unknown = await response.json().catch(() => ({}));

  if (!response.ok) {
    const data =
      body && typeof body === 'object'
        ? (body as Record<string, unknown>)
        : {};

    const message =
      typeof data.detail === 'string'
        ? data.detail
        : typeof data.message === 'string'
          ? data.message
          : `Request failed (${response.status})`;

    throw new Error(message);
  }

  return body as T;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  return {};
}

function getNumber(
  source: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const key of keys) {
    const value = source[key];

    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }

    if (typeof value === 'string' && value.trim() !== '') {
      const parsed = Number(value);

      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }

  return null;
}

function formatPercent(value: number | null): string {
  return value === null ? '--' : `${Math.round(value)}%`;
}

function getStatus(value: unknown): HealthStatus {
  if (typeof value === 'boolean') {
    return value ? 'up' : 'down';
  }

  if (typeof value === 'number') {
    return value > 0 ? 'up' : 'down';
  }

  if (typeof value === 'string') {
    const status = value.toLowerCase();

    if (
      ['up', 'online', 'healthy', 'ok', 'connected', 'success'].includes(
        status,
      )
    ) {
      return 'up';
    }

    if (
      ['down', 'offline', 'unhealthy', 'error', 'failed', 'disconnected'].includes(
        status,
      )
    ) {
      return 'down';
    }

    if (['running', 'active'].includes(status)) {
      return 'running';
    }

    if (['checking', 'loading'].includes(status)) {
      return 'checking';
    }
  }

  return 'unknown';
}

function StatusDot({ status }: { status: HealthStatus }) {
  return (
    <span
      className={`pc-status-dot pc-status-${status}`}
      aria-label={status}
      title={status}
    />
  );
}

function MetricCard({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description: string;
}) {
  return (
    <article className="pc-metric-card">
      <span className="pc-metric-label">{label}</span>
      <strong className="pc-metric-value">{value}</strong>
      <span className="pc-metric-description">{description}</span>
    </article>
  );
}

function DataList({
  value,
  emptyMessage,
}: {
  value: unknown;
  emptyMessage: string;
}) {
  const items = Array.isArray(value) ? value : [];

  if (!items.length) {
    return <p className="pc-empty-message">{emptyMessage}</p>;
  }

  return (
    <div className="pc-data-list">
      {items.map((item, index) => {
        const record = asRecord(item);
        const title =
          record.name ??
          record.title ??
          record.process ??
          record.host ??
          record.pid ??
          `Item ${index + 1}`;

        const subtitle =
          record.description ??
          record.path ??
          record.command ??
          record.status ??
          record.message ??
          '';

        return (
          <article className="pc-data-row" key={`${String(title)}-${index}`}>
            <div className="pc-data-row-main">
              <strong>{String(title)}</strong>
              {subtitle !== '' && (
                <span>{String(subtitle)}</span>
              )}
            </div>
            {record.status !== undefined && (
              <span className="pc-data-row-status">
                {String(record.status)}
              </span>
            )}
          </article>
        );
      })}
    </div>
  );
}

function PCIntelligence({ onBack }: PCIntelligenceProps) {
  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  const [system, setSystem] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [activeTab, setActiveTab] = useState<
    'overview' | 'processes' | 'network' | 'incidents'
  >('overview');

  const refresh = useCallback(async () => {
    try {
      const data = await fetchJSON<MonitorData>(
        `${API}/api/agent/monitor/status`,
      );

      setMonitor(data);
      setError('');
      setLastUpdated(new Date());

      try {
        const systemData = await fetchJSON<Record<string, unknown>>(
          `${API}/api/agent/system`,
        );

        setSystem(asRecord(systemData));
      } catch {
        // Monitoring data can still be shown if system enrichment fails.
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to connect to the local monitoring endpoint.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();

    const interval = window.setInterval(() => {
      void refresh();
    }, 3000);

    return () => {
      window.clearInterval(interval);
    };
  }, [refresh]);

  const monitorRecord = asRecord(monitor);
  const metrics = asRecord(monitorRecord.metrics);
  const nestedSystem = asRecord(monitorRecord.system);
  const systemRecord = system ?? {};

  const cpu =
    getNumber(metrics, ['cpu_percent', 'cpu', 'cpu_usage']) ??
    getNumber(nestedSystem, ['cpu_percent', 'cpu', 'cpu_usage']) ??
    getNumber(systemRecord, ['cpu_percent', 'cpu', 'cpu_usage']);

  const ram =
    getNumber(metrics, ['ram_percent', 'memory_percent', 'ram', 'memory']) ??
    getNumber(nestedSystem, [
      'ram_percent',
      'memory_percent',
      'ram',
      'memory',
    ]) ??
    getNumber(systemRecord, [
      'ram_percent',
      'memory_percent',
      'ram',
      'memory',
    ]);

  const disk =
    getNumber(metrics, ['disk_percent', 'disk', 'disk_usage']) ??
    getNumber(nestedSystem, ['disk_percent', 'disk', 'disk_usage']) ??
    getNumber(systemRecord, ['disk_percent', 'disk', 'disk_usage']);

  const processes =
    monitorRecord.processes ??
    monitorRecord.running_processes ??
    [];

  const incidents =
    monitorRecord.incidents ??
    monitorRecord.events ??
    [];

  const network =
    monitorRecord.network ??
    monitorRecord.network_info ??
    null;

  const engine =
    monitorRecord.engine ??
    monitorRecord.background_engine ??
    monitorRecord.agent ??
    null;

  const websites =
    monitorRecord.websites ??
    monitorRecord.website_health ??
    [];

  const applications =
    monitorRecord.applications ??
    monitorRecord.application_health ??
    [];

  const engineRecord = asRecord(engine);
  const engineStatus = getStatus(
    engineRecord.status ??
      engineRecord.running ??
      engineRecord.connected,
  );

  const networkRecord = asRecord(network);

  return (
    <main className="pc-intelligence-page">
      <header className="pc-intelligence-header">
        <button
          type="button"
          className="pc-back-button"
          onClick={onBack}
        >
          <span aria-hidden="true">←</span>
          Back to VANTEX
        </button>

        <div className="pc-dashboard-brand">
          <span className="pc-dashboard-brand-mark">V</span>
          <div>
            <strong>VANTEX</strong>
            <span>PC INTELLIGENCE</span>
          </div>
        </div>

        <div className="pc-live-indicator">
          <StatusDot status={error ? 'down' : loading ? 'checking' : 'up'} />
          <span>{error ? 'Disconnected' : loading ? 'Connecting' : 'Monitoring'}</span>
        </div>
      </header>

      <section className="pc-dashboard-content">
        <div className="pc-dashboard-heading">
          <div>
            <span className="pc-section-eyebrow">LOCAL SYSTEM MONITOR</span>
            <h1>PC Intelligence</h1>
            <p>
              Monitor your system, processes, network and recent incidents.
            </p>
          </div>

          <button
            type="button"
            className="pc-refresh-button"
            onClick={() => {
              setLoading(true);
              void refresh();
            }}
            disabled={loading}
          >
            ↻ Refresh
          </button>
        </div>

        {error && (
          <div className="pc-connection-error" role="alert">
            <strong>Monitor connection error</strong>
            <p>{error}</p>
            <span>
              Check that the FastAPI backend is running and that
              /api/agent/monitor/status is available.
            </span>
          </div>
        )}

        <div className="pc-metrics-grid">
          <MetricCard
            label="CPU USAGE"
            value={formatPercent(cpu)}
            description="Processor utilisation"
          />
          <MetricCard
            label="MEMORY USAGE"
            value={formatPercent(ram)}
            description="RAM utilisation"
          />
          <MetricCard
            label="DISK USAGE"
            value={formatPercent(disk)}
            description="Storage utilisation"
          />
        </div>

        <section className="pc-engine-panel">
          <div className="pc-panel-heading">
            <div>
              <span className="pc-section-eyebrow">LOCAL AGENT</span>
              <h2>Background Engine</h2>
            </div>
            <StatusDot status={engineStatus} />
          </div>

          <div className="pc-engine-details">
            <div>
              <span>Engine status</span>
              <strong>
                {engine === null
                  ? loading
                    ? 'Connecting…'
                    : error
                      ? 'Unavailable'
                      : 'Not reported'
                  : String(
                      engineRecord.status ??
                        (engineRecord.running === true
                          ? 'Running'
                          : engineRecord.connected === true
                            ? 'Connected'
                            : 'Status unknown'),
                    )}
              </strong>
            </div>

            <div>
              <span>Last update</span>
              <strong>
                {lastUpdated
                  ? lastUpdated.toLocaleTimeString()
                  : 'Waiting for data'}
              </strong>
            </div>
          </div>
        </section>

        <nav className="pc-dashboard-tabs" aria-label="PC dashboard sections">
          {(
            [
              ['overview', 'Overview'],
              ['processes', 'Processes'],
              ['network', 'Network'],
              ['incidents', 'Incidents'],
            ] as const
          ).map(([tab, label]) => (
            <button
              type="button"
              key={tab}
              className={activeTab === tab ? 'active' : ''}
              onClick={() => setActiveTab(tab)}
              aria-current={activeTab === tab ? 'page' : undefined}
            >
              {label}
            </button>
          ))}
        </nav>

        {activeTab === 'overview' && (
          <div className="pc-dashboard-panels">
            <section className="pc-panel">
              <div className="pc-panel-heading">
                <h2>Website Health</h2>
                <span>{Array.isArray(websites) ? websites.length : 0} items</span>
              </div>
              <DataList
                value={websites}
                emptyMessage="No website health checks were reported."
              />
            </section>

            <section className="pc-panel">
              <div className="pc-panel-heading">
                <h2>Application Health</h2>
                <span>
                  {Array.isArray(applications) ? applications.length : 0} items
                </span>
              </div>
              <DataList
                value={applications}
                emptyMessage="No application health checks were reported."
              />
            </section>

            <section className="pc-panel pc-panel-full">
              <div className="pc-panel-heading">
                <h2>Agent Snapshot</h2>
                <span>Latest data</span>
              </div>

              {Object.keys(systemRecord).length > 0 ? (
                <div className="pc-snapshot-grid">
                  {Object.entries(systemRecord)
                    .filter(
                      ([, value]) =>
                        typeof value === 'string' ||
                        typeof value === 'number' ||
                        typeof value === 'boolean',
                    )
                    .map(([key, value]) => (
                      <div className="pc-snapshot-item" key={key}>
                        <span>{key.replaceAll('_', ' ')}</span>
                        <strong>{String(value)}</strong>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="pc-empty-message">
                  System snapshot data is not available.
                </p>
              )}
            </section>
          </div>
        )}

        {activeTab === 'processes' && (
          <section className="pc-panel">
            <div className="pc-panel-heading">
              <h2>Running Processes</h2>
              <span>{Array.isArray(processes) ? processes.length : 0} items</span>
            </div>
            <DataList
              value={processes}
              emptyMessage="No process data was reported by the backend."
            />
          </section>
        )}

        {activeTab === 'network' && (
          <section className="pc-panel">
            <div className="pc-panel-heading">
              <h2>Network Intelligence</h2>
              <span>Local snapshot</span>
            </div>

            {Object.keys(networkRecord).length > 0 ? (
              <div className="pc-snapshot-grid">
                {Object.entries(networkRecord)
                  .filter(
                    ([, value]) =>
                      typeof value === 'string' ||
                      typeof value === 'number' ||
                      typeof value === 'boolean',
                  )
                  .map(([key, value]) => (
                    <div className="pc-snapshot-item" key={key}>
                      <span>{key.replaceAll('_', ' ')}</span>
                      <strong>{String(value)}</strong>
                    </div>
                  ))}
              </div>
            ) : network === null ? (
              <p className="pc-empty-message">
                No network data was reported by the backend.
              </p>
            ) : (
              <pre className="pc-json-view">
                {JSON.stringify(network, null, 2)}
              </pre>
            )}
          </section>
        )}

        {activeTab === 'incidents' && (
          <section className="pc-panel">
            <div className="pc-panel-heading">
              <h2>Recent Incidents</h2>
              <span>{Array.isArray(incidents) ? incidents.length : 0} items</span>
            </div>
            <DataList
              value={incidents}
              emptyMessage="No incidents were reported."
            />
          </section>
        )}

        <footer className="pc-dashboard-footer">
          <span>VANTEX AI</span>
          <span>LOCAL-FIRST INTELLIGENCE</span>
          <span>
            {lastUpdated
              ? `Updated ${lastUpdated.toLocaleTimeString()}`
              : 'Awaiting telemetry'}
          </span>
        </footer>
      </section>
    </main>
  );
}

export default function App() {
  const [page, setPage] = useState<'home' | 'intelligence'>('home');

  return (
    <main className="vantex-app">
      {page === 'home' ? (
        <Home onOpenIntelligence={() => setPage('intelligence')} />
      ) : (
        <PCIntelligence onBack={() => setPage('home')} />
      )}
    </main>
  );
}
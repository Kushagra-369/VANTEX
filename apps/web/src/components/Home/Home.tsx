import { useEffect, useState } from 'react'
import './Home.css'

type HomeProps = {
  onOpenIntelligence: () => void
}

type ApiState = 'checking' | 'online' | 'offline'

type CommandResult = {
  command: string
  action: string
  result: unknown
}

export default function Home({ onOpenIntelligence }: HomeProps) {
  const [apiState, setApiState] = useState<ApiState>('checking')
  const [command, setCommand] = useState('')
  const [result, setResult] = useState<CommandResult | null>(null)
  const [commandError, setCommandError] = useState('')
  const [isRunning, setIsRunning] = useState(false)

  useEffect(() => {
    let active = true

    const checkApi = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/health')
        if (!response.ok) throw new Error('API unavailable')
        if (active) setApiState('online')
      } catch {
        if (active) setApiState('offline')
      }
    }

    void checkApi()
    const interval = window.setInterval(() => void checkApi(), 5000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  const submitCommand = async (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault()

    const value = command.trim()
    if (!value || isRunning) return

    setIsRunning(true)
    setCommandError('')
    setResult(null)

    try {
      const response = await fetch(
        'http://127.0.0.1:8000/api/agent/command',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: value }),
        },
      )

      const data: unknown = await response.json()

      if (!response.ok) {
        const message =
          typeof data === 'object' &&
          data !== null &&
          'detail' in data
            ? String(data.detail)
            : 'Command failed.'

        throw new Error(message)
      }

      setResult(data as CommandResult)
    } catch (error) {
      setCommandError(
        error instanceof Error
          ? error.message
          : 'Could not reach VANTEX API.',
      )
    } finally {
      setIsRunning(false)
    }
  }

  const resetHome = () => {
    setCommand('')
    setResult(null)
    setCommandError('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="home-shell">
      <header className="home-topbar">
        <button
          className="brand"
          onClick={resetHome}
          aria-label="VANTEX home"
        >
          <span className="brand-symbol">V</span>
          <span>VANTEX</span>
        </button>

        <div className="topbar-actions">
          <span className="api-indicator">
            <span className={`status-dot ${apiState}`} />
            API {apiState === 'checking' ? 'CHECKING' : apiState.toUpperCase()}
          </span>

          <button
            className="icon-button"
            onClick={onOpenIntelligence}
            aria-label="Open PC Intelligence"
            title="PC Intelligence"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="4" width="18" height="13" rx="2" />
              <path d="M8 21h8M12 17v4M7 9h3M7 12h6M16 9h1" />
            </svg>
          </button>
        </div>
      </header>

      <main className="command-main">
        <div className="hero-orb" aria-hidden="true">
          <div className="orb-core">
            <span>V</span>
          </div>
        </div>

        <div className="hero-copy">
          <span className="eyebrow">
            YOUR PERSONAL AUTOMATION SYSTEM
          </span>

          <h1>
            What should I <span>do for you?</span>
          </h1>

          <p>
            One command. One workspace. Your PC, projects and workflows.
          </p>
        </div>

        <form className="command-box" onSubmit={submitCommand}>
          <label className="visually-hidden" htmlFor="vantex-command">
            Enter a command for VANTEX
          </label>

          <textarea
            id="vantex-command"
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder="Try: system status, find file Home.tsx..."
            rows={3}
            disabled={isRunning}
          />

          <div className="command-toolbar">
            <span className="command-hint">
              ENTER TO SUBMIT · SHIFT + ENTER FOR NEW LINE
            </span>

            <button
              className="send-button"
              type="submit"
              disabled={!command.trim() || isRunning}
              aria-label="Submit command"
            >
              {isRunning ? '…' : '↑'}
            </button>
          </div>
        </form>

        {isRunning && (
          <section className="task-preview" aria-live="polite">
            <div className="task-preview-heading">VANTEX IS WORKING</div>
            <p>Executing your requested operation…</p>
          </section>
        )}

        {commandError && (
          <section className="task-preview" role="alert">
            <div className="task-preview-heading">COMMAND FAILED</div>
            <p>{commandError}</p>
          </section>
        )}

        {result !== null && (
          <section className="task-preview" aria-live="polite">
            <div className="task-preview-heading">
              COMMAND COMPLETED
            </div>

            <p>{result.command}</p>

            <pre className="command-result">
              {JSON.stringify(result, null, 2)}
            </pre>
          </section>
        )}

        <div className="quick-actions">
          <button
            className="quick-action"
            onClick={() => setCommand('test website http://localhost:5173')}
          >
            <span className="quick-icon">⌘</span>
            <span>Test a website</span>
          </button>

          <button
            className="quick-action"
            onClick={() => setCommand('find file Home.tsx')}
          >
            <span className="quick-icon">⌕</span>
            <span>Find a file</span>
          </button>

          <button
            className="quick-action"
            onClick={onOpenIntelligence}
          >
            <span className="quick-icon">⌁</span>
            <span>PC Intelligence</span>
          </button>
        </div>

        <footer className="home-footer">
          <span>VANTEX / LOCAL-FIRST AUTOMATION</span>
          <span>YOU STAY IN CONTROL</span>
        </footer>
      </main>
    </div>
  )
}
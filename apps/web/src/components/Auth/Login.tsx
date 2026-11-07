
import { useState } from 'react';
import {Turnstile} from '@marsidev/react-turnstile';
import { supabase } from '../../lib/supabase';
import './Login.css';

type LoginProps = {
  onContinueAsGuest: () => void;
};

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV
    ? 'http://127.0.0.1:8000'
    : 'https://vantex-2d4l.onrender.com')
).replace(/\/$/, '');

const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';

export default function Login({ onContinueAsGuest }: LoginProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [token, setToken] = useState('');
  const [honeypot, setHoneypot] = useState('');

  async function verifyHuman(): Promise<boolean> {
    setError('');

    if (honeypot.trim()) {
      setError('Verification failed. Please refresh and try again.');
      setToken('');
      return false;
    }

    if (!SITE_KEY || !token) {
      setError('Please complete the security verification first.');
      return false;
    }

    try {
      const response = await fetch(
        `${API_BASE}/api/security/verify-turnstile`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token,
            website: honeypot,
          }),
        },
      );

      const data = await response.json().catch(() => ({}));

      if (!response.ok || data.success !== true) {
        setToken('');
        setError(
          data.detail || 'Verification failed. Please try again.',
        );
        return false;
      }

      setToken('');
      return true;
    } catch {
      setError('Cannot reach the security server. Please try again.');
      setToken('');
      return false;
    }
  }

  async function handleGoogleLogin() {
    if (loading) return;

    setLoading(true);
    try {
      if (!(await verifyHuman())) return;

      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin,
        },
      });

      if (error) {
        setError(error.message);
      }
    } catch {
      setError('Unable to connect. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  async function handleGuest() {
    if (loading) return;

    setLoading(true);
    try {
      if (!(await verifyHuman())) return;
      onContinueAsGuest();
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="vantex-login">
      <section className="vantex-login-card">
        <div className="vantex-login-brand">VANTEX</div>

        <p className="vantex-login-subtitle">
          Your AI workspace. Your command center.
        </p>

        <div className="vantex-honeypot" aria-hidden="true">
          <label>
            Leave this field empty
            <input
              type="text"
              name="website"
              value={honeypot}
              onChange={(event) => setHoneypot(event.target.value)}
              tabIndex={-1}
              autoComplete="off"
            />
          </label>
        </div>

        <div className="vantex-turnstile">
          {SITE_KEY ? (
            <Turnstile
              siteKey={SITE_KEY}
              options={{ theme: 'dark', action: 'login' }}
              onSuccess={(value: string) => {
                setToken(value);
                setError('');
              }}
              onExpire={() => setToken('')}
              onError={() => {
                setToken('');
                setError('Security verification failed to load. Refresh and retry.');
              }}
            />
          ) : (
            <p className="vantex-login-error">
              Turnstile Site Key is missing. Check .env.local.
            </p>
          )}
        </div>

        <button
          className="vantex-google-button"
          type="button"
          onClick={handleGoogleLogin}
          disabled={loading || !SITE_KEY || !token}
        >
          {loading ? 'Verifying...' : 'Continue with Google'}
        </button>

        <div className="vantex-login-divider">
          <span>OR</span>
        </div>

        <button
          className="vantex-guest-button"
          type="button"
          onClick={handleGuest}
          disabled={loading || !SITE_KEY || !token}
        >
          Continue as Guest
          <span className="vantex-guest-label">
            Limited access · No saved data
          </span>
        </button>

        {error && (
          <p className="vantex-login-error" role="alert">
            {error}
          </p>
        )}

        <p className="vantex-login-note">
          Sign in for your personal workspace, or explore VANTEX as a guest.
        </p>
      </section>
    </main>
  );
}

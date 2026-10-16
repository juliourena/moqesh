import { useState, type FormEvent } from 'react';
import { Shield, LogIn } from 'lucide-react';
import { api } from '../services/api';

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api.auth.login(username.trim(), password);
      onSuccess();
    } catch {
      setError('Credenciales inválidas');
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2.5 mb-6">
          <Shield className="w-7 h-7 text-accent" />
          <span className="text-xl font-semibold tracking-tight">
            Moqesh <span className="text-accent">AI</span>
          </span>
        </div>
        <form
          onSubmit={submit}
          className="bg-surface border border-border rounded-lg p-6 space-y-4 shadow-xl"
        >
          <div>
            <h1 className="text-base font-medium">Acceso al panel</h1>
            <p className="text-xs text-fg-muted mt-0.5">Solo operadores autorizados.</p>
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs text-fg-muted" htmlFor="u">Usuario</label>
            <input
              id="u"
              autoFocus
              autoComplete="username"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full px-3 py-2 bg-bg border border-border rounded-md text-sm focus:outline-none focus:border-accent"
            />
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs text-fg-muted" htmlFor="p">Contraseña</label>
            <input
              id="p"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-bg border border-border rounded-md text-sm focus:outline-none focus:border-accent"
            />
          </div>
          {error && <p className="text-xs text-red">{error}</p>}
          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-accent text-bg rounded-md text-sm font-medium hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <LogIn className="w-4 h-4" />
            {busy ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  );
}

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type Me } from '../services/api';
import { Login } from '../pages/Login';

interface AuthCtx {
  user: Me | null;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({ user: null, logout: async () => {} });

export const useAuth = () => useContext(Ctx);

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'loading' | 'in' | 'out'>('loading');
  const [user, setUser] = useState<Me | null>(null);

  const check = () =>
    api.auth
      .me()
      .then(u => {
        setUser(u);
        setState('in');
      })
      .catch(() => {
        setUser(null);
        setState('out');
      });

  useEffect(() => {
    check();
    // Cualquier 401 en la app (sesión caducada) nos devuelve al login.
    const onUnauth = () => {
      setUser(null);
      setState('out');
    };
    window.addEventListener('moqesh:unauthorized', onUnauth);
    return () => window.removeEventListener('moqesh:unauthorized', onUnauth);
  }, []);

  const logout = async () => {
    try {
      await api.auth.logout();
    } catch {
      /* da igual: limpiamos el estado local de todos modos */
    }
    setUser(null);
    setState('out');
  };

  if (state === 'loading') {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center text-fg-muted text-sm">
        Cargando…
      </div>
    );
  }
  if (state === 'out') {
    return <Login onSuccess={check} />;
  }
  return <Ctx.Provider value={{ user, logout }}>{children}</Ctx.Provider>;
}

import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, List, Users, Shield, Bell, SlidersHorizontal, Hexagon, Flame, Swords, Ban, Radar, LogOut,
} from 'lucide-react';
import { useAuth } from '../AuthGate';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/requests', icon: List, label: 'Requests' },
  { to: '/sessions', icon: Users, label: 'Sessions' },
  { to: '/token-exhaust', icon: Flame, label: 'Token Exhaust' },
  { to: '/scenarios', icon: Swords, label: 'Escenarios CTF' },
  { to: '/honeypots', icon: Hexagon, label: 'Honeypots' },
  { to: '/sensors', icon: Radar, label: 'Sensores' },
  { to: '/alerts', icon: Bell, label: 'Alerts' },
  { to: '/blocks', icon: Ban, label: 'Bloqueos' },
  { to: '/rules', icon: SlidersHorizontal, label: 'Rules' },
];

export function Sidebar() {
  const { user, logout } = useAuth();
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-56 bg-surface border-r border-border flex flex-col z-30">
      <div className="h-14 flex items-center gap-2.5 px-5 border-b border-border">
        <Shield className="w-6 h-6 text-accent" />
        <span className="text-base font-semibold tracking-tight">
          Moqesh <span className="text-accent">AI</span>
        </span>
      </div>
      <nav className="flex-1 py-3 px-3 space-y-0.5">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-accent/15 text-accent font-medium'
                  : 'text-fg-muted hover:text-fg hover:bg-surface-alt'
              }`
            }
          >
            <Icon className="w-4 h-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-border space-y-2">
        <div className="flex items-center justify-between gap-2 px-1">
          <div className="min-w-0">
            <div className="text-xs font-medium truncate">{user?.username ?? '—'}</div>
            <div className="text-[10px] text-fg-muted uppercase tracking-wider">{user?.role ?? ''}</div>
          </div>
          <button
            onClick={() => { void logout(); }}
            title="Cerrar sesión"
            className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-fg-muted hover:text-red hover:bg-surface-alt transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" />
            Salir
          </button>
        </div>
        <p className="text-[10px] text-fg-muted font-mono px-1">v0.1.0-alpha</p>
      </div>
    </aside>
  );
}

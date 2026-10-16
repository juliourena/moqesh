import { useEffect, useState } from 'react';
import { Check, AlertTriangle, ShieldAlert, AlertCircle, Info } from 'lucide-react';
import { api } from '../services/api';
import type { AlertSummary } from '../types';

const severityConfig: Record<string, { icon: typeof AlertTriangle; class: string; bg: string }> = {
  Critical: { icon: ShieldAlert, class: 'text-red', bg: 'bg-red/10' },
  High: { icon: AlertTriangle, class: 'text-amber', bg: 'bg-amber/10' },
  Medium: { icon: AlertCircle, class: 'text-blue', bg: 'bg-blue/10' },
  Low: { icon: Info, class: 'text-fg-muted', bg: 'bg-surface-alt' },
};

export function Alerts() {
  const [alerts, setAlerts] = useState<AlertSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');

  const load = () => {
    const params: { severity?: string; acknowledged?: boolean; limit: number } = { limit: 50 };
    if (filter === 'unresolved') params.acknowledged = false;
    if (['Critical', 'High', 'Medium', 'Low'].includes(filter)) params.severity = filter;
    api.alerts.list(params)
      .then(setAlerts)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, [filter]);

  const handleAcknowledge = async (id: number) => {
    await api.alerts.acknowledge(id);
    load();
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Alertas</h1>
        <p className="text-sm text-fg-muted mt-1">Centro de alertas de detección</p>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        {['all', 'unresolved', 'Critical', 'High', 'Medium', 'Low'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              filter === f ? 'bg-accent text-bg' : 'bg-surface-alt text-fg-muted hover:text-fg'
            }`}
          >
            {f === 'all' ? 'Todas' : f === 'unresolved' ? 'Sin resolver' : f}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {alerts.map(alert => {
          const config = severityConfig[alert.severity] || severityConfig.Low;
          const Icon = config.icon;
          return (
            <div key={alert.id} className={`flex items-start gap-4 p-4 rounded-lg bg-surface border border-border ${alert.acknowledged ? 'opacity-50' : ''}`}>
              <div className={`p-2 rounded-md ${config.bg}`}>
                <Icon className={`w-4 h-4 ${config.class}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">{alert.title}</p>
                <p className="text-xs text-fg-muted mt-1">{new Date(alert.createdAt).toLocaleString()}</p>
              </div>
              {!alert.acknowledged && (
                <button
                  onClick={() => handleAcknowledge(alert.id)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-green/10 text-green hover:bg-green/20 shrink-0"
                >
                  <Check className="w-3 h-3" /> Acknowledge
                </button>
              )}
            </div>
          );
        })}
        {alerts.length === 0 && !loading && (
          <div className="text-center py-12 text-fg-muted">
            <p className="text-sm">Sin alertas</p>
          </div>
        )}
      </div>
    </div>
  );
}

import { AlertTriangle, AlertCircle, Info, ShieldAlert } from 'lucide-react';
import type { AlertSummary } from '../../types';

interface Props {
  data: AlertSummary[];
}

const severityConfig: Record<string, { icon: typeof AlertTriangle; class: string }> = {
  Critical: { icon: ShieldAlert, class: 'text-red' },
  High: { icon: AlertTriangle, class: 'text-amber' },
  Medium: { icon: AlertCircle, class: 'text-blue' },
  Low: { icon: Info, class: 'text-fg-muted' },
};

export function RecentAlerts({ data }: Props) {
  return (
    <div className="bg-surface rounded-lg border border-border p-5">
      <h3 className="text-sm font-medium text-fg-muted mb-4">Alertas recientes</h3>
      <div className="space-y-2">
        {data.map(alert => {
          const config = severityConfig[alert.severity] || severityConfig.Low;
          const Icon = config.icon;
          return (
            <div
              key={alert.id}
              className={`flex items-start gap-3 p-3 rounded-md bg-surface-alt/50 ${
                alert.acknowledged ? 'opacity-50' : ''
              }`}
            >
              <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${config.class}`} />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{alert.title}</p>
                <p className="text-xs text-fg-muted">
                  {new Date(alert.createdAt).toLocaleString()}
                </p>
              </div>
              <span className={`text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded ${config.class}`}>
                {alert.severity}
              </span>
            </div>
          );
        })}
        {data.length === 0 && (
          <p className="text-sm text-fg-muted text-center py-6">Sin alertas</p>
        )}
      </div>
    </div>
  );
}

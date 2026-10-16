import type { TopSourceEntry } from '../../types';

interface Props {
  data: TopSourceEntry[];
}

function scoreBadge(score: number) {
  if (score >= 0.8) return 'bg-red/20 text-red';
  if (score >= 0.6) return 'bg-amber/20 text-amber';
  if (score >= 0.4) return 'bg-blue/20 text-blue';
  return 'bg-green/20 text-green';
}

export function TopSources({ data }: Props) {
  const max = Math.max(...data.map(d => d.requestCount), 1);

  return (
    <div className="bg-surface rounded-lg border border-border p-5">
      <h3 className="text-sm font-medium text-fg-muted mb-4">Top Source IPs</h3>
      <div className="space-y-3">
        {data.slice(0, 8).map(entry => (
          <div key={entry.ip} className="flex items-center gap-3">
            <code className="text-xs text-fg-muted w-28 shrink-0 truncate">{entry.ip}</code>
            <div className="flex-1 h-4 bg-surface-alt rounded-sm overflow-hidden">
              <div
                className="h-full bg-accent/40 rounded-sm"
                style={{ width: `${(entry.requestCount / max) * 100}%` }}
              />
            </div>
            <span className="text-xs font-mono w-8 text-right">{entry.requestCount}</span>
            <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${scoreBadge(entry.maxScore)}`}>
              {entry.maxScore.toFixed(1)}
            </span>
          </div>
        ))}
        {data.length === 0 && (
          <p className="text-sm text-fg-muted text-center py-4">Sin datos aún</p>
        )}
      </div>
    </div>
  );
}

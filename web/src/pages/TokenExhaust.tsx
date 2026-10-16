import { useEffect, useState } from 'react';
import { Flame, Clock, Network, Bot } from 'lucide-react';
import { api } from '../services/api';
import type { TokenExhaustOverview } from '../types';
import { INTENSITY_HINTS, INTENSITY_LABELS, intensityBadge, intensityFromScore } from '../lib/intensity';

function fmtMs(ms: number) {
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = s / 60;
  if (m < 60) return `${m.toFixed(1)} min`;
  return `${(m / 60).toFixed(1)} h`;
}

function verdictBadge(v: string) {
  switch (v) {
    case 'AiConfirmed': return 'bg-red/20 text-red border-red/30';
    case 'HumanLikely': return 'bg-green/20 text-green border-green/30';
    default: return 'bg-surface-alt text-fg-muted border-border';
  }
}

export function TokenExhaust() {
  const [data, setData] = useState<TokenExhaustOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => api.dashboard.tokenExhaust().then(setData).catch(() => {}).finally(() => setLoading(false));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const kpis = [
    { icon: Flame, label: 'Tokens quemados (est.)', value: data ? data.totalTokensBurned.toLocaleString() : '—', color: 'text-red' },
    { icon: Clock, label: 'Tiempo desperdiciado', value: data ? fmtMs(data.totalTimeWastedMs) : '—', color: 'text-amber' },
    { icon: Network, label: 'Nodos servidos', value: data ? data.totalNodesServed.toLocaleString() : '—', color: 'text-blue' },
    { icon: Bot, label: 'Sesiones atrapadas', value: data ? String(data.sessionsEngaged) : '—', color: 'text-accent' },
  ];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Token Exhaust</h1>
        <p className="text-sm text-fg-muted mt-1">
          Recursos que el laberinto le hizo consumir a los agentes: tokens, tiempo y profundidad.
        </p>
        <div className="flex flex-wrap gap-2 mt-3">
          {INTENSITY_LABELS.map((label, lvl) => (
            <span
              key={label}
              className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${intensityBadge(lvl)}`}
              title={INTENSITY_HINTS[lvl]}
            >
              {lvl} · {label}
            </span>
          ))}
          <span className="text-[11px] text-fg-muted self-center">
            intensidad adaptativa: coherente por defecto → cebo + tarpit al confirmar agente
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {kpis.map(k => (
          <div key={k.label} className="bg-surface border border-border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <k.icon className={`w-4 h-4 ${k.color}`} />
              <span className="text-xs text-fg-muted">{k.label}</span>
            </div>
            <div className="text-2xl font-semibold font-mono tabular-nums">{k.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-surface border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-medium">Top consumidores</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-fg-muted uppercase tracking-wider">
                  <th className="text-left px-4 py-2 font-medium">Origen</th>
                  <th className="text-right px-4 py-2 font-medium">Tokens</th>
                  <th className="text-right px-4 py-2 font-medium">Tiempo</th>
                  <th className="text-right px-4 py-2 font-medium">Nodos</th>
                  <th className="text-right px-4 py-2 font-medium">Prof.</th>
                  <th className="text-right px-4 py-2 font-medium">Score</th>
                  <th className="text-left px-4 py-2 font-medium">Intens.</th>
                  <th className="text-left px-4 py-2 font-medium">Veredicto</th>
                </tr>
              </thead>
              <tbody>
                {data?.topBurners.map(b => (
                  <tr key={b.ip} className="border-b border-border/50 hover:bg-surface-alt/50">
                    <td className="px-4 py-2 font-mono text-xs">{b.ip}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{b.tokens.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-fg-muted">{fmtMs(b.timeWastedMs)}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{b.nodes}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{b.maxDepth}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">{b.score.toFixed(2)}</td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${intensityBadge(intensityFromScore(b.score))}`}>
                        {intensityFromScore(b.score)}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${verdictBadge(b.verdict)}`}>
                        {b.verdict}
                      </span>
                    </td>
                  </tr>
                ))}
                {(!data || data.topBurners.length === 0) && !loading && (
                  <tr><td colSpan={8} className="px-4 py-8 text-center text-fg-muted text-sm">Aún no hay sesiones atrapadas</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-medium">Por modelo (pruebas con IA)</h3>
          </div>
          <div className="p-4 space-y-3">
            {data?.byModel.map(m => (
              <div key={m.model} className="border border-border/60 rounded-md p-3">
                <div className="font-mono text-xs text-accent break-all mb-1">{m.model}</div>
                <div className="flex justify-between text-xs text-fg-muted">
                  <span>{m.sessions} sesiones</span>
                  <span className="font-mono">{m.tokens.toLocaleString()} tok</span>
                </div>
                <div className="text-xs text-fg-muted mt-1">score medio: <span className="font-mono text-fg">{m.avgScore.toFixed(2)}</span></div>
              </div>
            ))}
            {(!data || data.byModel.length === 0) && (
              <p className="text-xs text-fg-muted text-center py-6">
                Sin atribución de modelo todavía. Ejecuta el harness de agente (Claude local / OpenRouter)
                para poblar esta sección.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

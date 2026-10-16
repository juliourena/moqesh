import { useEffect, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { api } from '../services/api';
import type { SessionDto, SessionDetailDto } from '../types';
import { INTENSITY_LABELS, intensityBadge, intensityFromScore } from '../lib/intensity';

function scoreBadge(score: number) {
  if (score >= 0.8) return 'bg-red/20 text-red border-red/30';
  if (score >= 0.6) return 'bg-amber/20 text-amber border-amber/30';
  if (score >= 0.4) return 'bg-blue/20 text-blue border-blue/30';
  return 'bg-green/20 text-green border-green/30';
}

function verdictBadge(v: string) {
  switch (v) {
    case 'AiConfirmed': return 'bg-red/20 text-red';
    case 'HumanLikely': return 'bg-green/20 text-green';
    default: return 'bg-surface-alt text-fg-muted';
  }
}

function SessionRow({ session }: { session: SessionDto }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<SessionDetailDto | null>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) api.sessions.get(session.id).then(setDetail).catch(() => {});
  };

  const rules = (session.matchedRules ?? '').split(',').filter(Boolean);

  return (
    <>
      <tr onClick={toggle} className="border-b border-border/50 hover:bg-surface-alt/50 transition-colors cursor-pointer">
        <td className="px-4 py-2.5">
          <ChevronRight className={`w-3.5 h-3.5 text-fg-muted transition-transform ${open ? 'rotate-90' : ''}`} />
        </td>
        <td className="px-4 py-2.5 font-mono text-xs">{session.sourceIp}</td>
        <td className="px-4 py-2.5">
          <span className={`text-xs font-mono font-medium px-2 py-0.5 rounded border ${scoreBadge(session.aiProbabilityScore)}`}>
            {session.aiProbabilityScore.toFixed(2)}
          </span>
        </td>
        <td className="px-4 py-2.5">
          {(() => {
            const lvl = intensityFromScore(session.aiProbabilityScore);
            return (
              <span
                className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded border ${intensityBadge(lvl)}`}
                title={`Intensidad adaptativa ${lvl}/3`}
              >
                {lvl} · {INTENSITY_LABELS[lvl]}
              </span>
            );
          })()}
        </td>
        <td className="px-4 py-2.5">
          <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${verdictBadge(session.verdict)}`}>
            {session.verdict}
          </span>
        </td>
        <td className="px-4 py-2.5 font-mono text-xs">{session.requestCount}</td>
        <td className="px-4 py-2.5 font-mono text-xs">{session.maxDepthReached}</td>
        <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{session.tokensEstimated.toLocaleString()}</td>
        <td className="px-4 py-2.5 text-xs text-fg-muted max-w-[180px] truncate" title={session.userAgent ?? ''}>
          {session.userAgent || '—'}
        </td>
      </tr>
      {open && (
        <tr className="bg-surface-alt/30">
          <td colSpan={9} className="px-6 py-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-1 space-y-3">
                <div>
                  <div className="text-xs text-fg-muted mb-1">Reglas disparadas</div>
                  <div className="flex flex-wrap gap-1">
                    {rules.length > 0 ? rules.map(r => (
                      <span key={r} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface border border-border">{r}</span>
                    )) : <span className="text-xs text-fg-muted">ninguna</span>}
                  </div>
                </div>
                {session.verdictReasoning && (
                  <div>
                    <div className="text-xs text-fg-muted mb-1">Razonamiento IA ({session.verdictConfidence.toFixed(2)})</div>
                    <p className="text-xs">{session.verdictReasoning}</p>
                  </div>
                )}
                {session.modelAttribution && (
                  <div>
                    <div className="text-xs text-fg-muted mb-1">Modelo</div>
                    <p className="text-xs font-mono text-accent break-all">{session.modelAttribution}</p>
                  </div>
                )}
                {detail?.progress && (
                  <div>
                    <div className="text-xs text-fg-muted mb-1">Progreso CTF</div>
                    <div className="text-xs space-y-0.5">
                      <div>etapa alcanzada: <span className="font-mono text-fg">{detail.progress.stageReached}</span></div>
                      {detail.progress.credentialsObtained && <div>creds obtenidas: <span className="font-mono text-amber">{detail.progress.credentialsObtained}</span></div>}
                      {detail.progress.credentialsUsed && <div className="text-red">creds USADAS: <span className="font-mono">{detail.progress.credentialsUsed}</span></div>}
                      <div className="text-fg-muted">rutas ocultas: {detail.progress.hiddenHits} · decompile: {detail.progress.decompileFollow ? 'sí' : 'no'} · fallos auth: {detail.progress.failedAuthAttempts}</div>
                    </div>
                  </div>
                )}
                <div className="flex gap-4 text-xs text-fg-muted">
                  <span>nodos: <span className="font-mono text-fg">{session.nodesServed}</span></span>
                  <span>tiempo: <span className="font-mono text-fg">{session.timeWastedMs} ms</span></span>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); api.blocks.block(session.sourceIp, `bloqueo manual desde sesión (score ${session.aiProbabilityScore.toFixed(2)})`).then(() => alert(`IP ${session.sourceIp} bloqueada`)); }}
                  className="mt-1 flex items-center gap-1.5 px-2.5 py-1 bg-red/10 text-red rounded text-xs font-medium hover:bg-red/20 w-fit">
                  Bloquear {session.sourceIp}
                </button>
              </div>
              <div className="lg:col-span-2">
                <div className="text-xs text-fg-muted mb-1">Timeline de requests</div>
                <div className="max-h-64 overflow-y-auto font-mono text-[11px] space-y-0.5 pr-2">
                  {detail?.requests.map((r, i) => {
                    const prev = i > 0 ? new Date(detail.requests[i - 1].timestamp).getTime() : 0;
                    const dt = prev ? ((new Date(r.timestamp).getTime() - prev) / 1000).toFixed(1) : '0.0';
                    return (
                      <div key={r.id} className="flex gap-2 items-baseline">
                        <span className="text-fg-muted w-10 shrink-0 text-right">+{dt}s</span>
                        <span className={r.responseCode >= 400 ? 'text-amber' : 'text-green'}>{r.responseCode}</span>
                        <span className="text-fg-muted">{r.method}</span>
                        <span className="truncate">{r.path}</span>
                      </div>
                    );
                  })}
                  {!detail && <span className="text-fg-muted">cargando…</span>}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function Sessions() {
  const [sessions, setSessions] = useState<SessionDto[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => api.sessions.list({ limit: 50 }).then(setSessions).catch(() => {}).finally(() => setLoading(false));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Sessions</h1>
        <p className="text-sm text-fg-muted mt-1">Sesiones agrupadas por IP — clic para ver el timeline y el veredicto</p>
      </div>

      <div className="bg-surface rounded-lg border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-medium text-fg-muted uppercase tracking-wider">
                <th className="w-8 px-4 py-3"></th>
                <th className="text-left px-4 py-3">Source IP</th>
                <th className="text-left px-4 py-3">AI Score</th>
                <th className="text-left px-4 py-3">Intensidad</th>
                <th className="text-left px-4 py-3">Veredicto</th>
                <th className="text-left px-4 py-3">Requests</th>
                <th className="text-left px-4 py-3">Prof.</th>
                <th className="text-left px-4 py-3">Tokens Est.</th>
                <th className="text-left px-4 py-3">User-Agent</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map(session => <SessionRow key={session.id} session={session} />)}
              {sessions.length === 0 && !loading && (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-fg-muted text-sm">Sin sesiones detectadas</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

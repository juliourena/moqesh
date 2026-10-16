import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Plus, Power, RefreshCw, Trash2, Copy, Check, X, Download, Loader2,
  CheckCircle2, AlertTriangle, Terminal, ArrowRight, Package, Cpu, Radar, Server,
} from 'lucide-react';
import { api, downloads } from '../services/api';
import { connectLive } from '../services/realtime';
import type { SensorCreated, SensorDto, SensorBundleDto, SensorInstallInfo, SensorKind } from '../types';

const GEN_MODES = ['Template', 'Mimic', 'Static'];

function relTime(iso: string | null): string {
  if (!iso) return 'nunca';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'nunca';
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return `hace ${s}s`;
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

const STATUS: Record<string, { dot: string; label: string }> = {
  online: { dot: 'bg-green', label: 'online' },
  offline: { dot: 'bg-red', label: 'offline' },
  unknown: { dot: 'bg-fg-muted', label: 'desconocido' },
};

const KIND_META: Record<SensorKind, { icon: typeof Cpu; label: string }> = {
  agent: { icon: Cpu, label: 'Agente' },
  agentless: { icon: Radar, label: 'Sin agente' },
  local: { icon: Server, label: 'Local' },
};

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    }).catch(() => {});
  };
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-surface-alt text-fg-muted hover:text-accent shrink-0"
      title="Copiar"
    >
      {done ? <Check className="w-3.5 h-3.5 text-green" /> : <Copy className="w-3.5 h-3.5" />}
      {label && <span>{done ? 'Copiado' : label}</span>}
    </button>
  );
}

function CommandBlock({ title, command }: { title: string; command: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs text-fg-muted mb-1">
        <Terminal className="w-3.5 h-3.5" /> {title}
      </div>
      <div className="flex items-start gap-2 bg-bg border border-border rounded p-2.5">
        <code className="flex-1 font-mono text-[11px] text-fg break-all whitespace-pre-wrap">{command}</code>
        <CopyButton text={command} />
      </div>
    </div>
  );
}

function recommend(canInstall: boolean, credReuse: boolean, stealth: boolean): { kind: SensorKind; reason: string } {
  if (!canInstall)
    return { kind: 'agentless', reason: 'No puedes instalar software en el host, así que el modo sin agente (cebos en un ZIP + una tarea cron que reenvía los logs) es la única vía viable.' };
  if (credReuse)
    return { kind: 'agent', reason: 'La detección de reuso de credenciales y los retos tipo CTF necesitan el honeypot inline del agente, que correlaciona peticiones y credenciales en tiempo real.' };
  if (stealth)
    return { kind: 'agentless', reason: 'Si el sigilo es prioritario, el modo sin agente no deja ningún proceso instalado: solo archivos cebo y una tarea cron discreta.' };
  return { kind: 'agent', reason: 'Puedes instalar software y no hay restricciones especiales: el agente da la mejor cobertura y señales en tiempo real.' };
}

// ------- Asistente de alta -------

type Phase = 'questions' | 'form' | 'created';

function YesNo({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-sm">{label}</span>
      <div className="flex gap-1 shrink-0">
        {([['Sí', true], ['No', false]] as const).map(([t, v]) => (
          <button
            key={t}
            onClick={() => onChange(v)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              value === v ? 'bg-accent text-bg' : 'bg-surface-alt text-fg-muted hover:text-fg'
            }`}
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}

function AddSensorWizard({ liveSignal, onClose, onCreated }: { liveSignal: number; onClose: () => void; onCreated: () => void }) {
  const [phase, setPhase] = useState<Phase>('questions');
  // preguntas de recomendación
  const [canInstall, setCanInstall] = useState<boolean | null>(null);
  const [credReuse, setCredReuse] = useState<boolean | null>(null);
  const [stealth, setStealth] = useState<boolean | null>(null);
  // formulario
  const [name, setName] = useState('');
  const [kind, setKind] = useState<SensorKind>('agent');
  const [coveredUrl, setCoveredUrl] = useState('');
  const [coveredApp, setCoveredApp] = useState('');
  const [basePath, setBasePath] = useState('/');
  const [genMode, setGenMode] = useState('Template');
  const [realism, setRealism] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // resultado
  const [created, setCreated] = useState<SensorCreated | null>(null);
  const [install, setInstall] = useState<SensorInstallInfo | null>(null);
  const [connected, setConnected] = useState(false);
  const [bundles, setBundles] = useState<SensorBundleDto[]>([]);
  const [genning, setGenning] = useState(false);

  const rec = canInstall === null || credReuse === null || stealth === null
    ? null
    : recommend(canInstall, credReuse, stealth);

  const goForm = () => {
    if (rec) setKind(rec.kind);
    setPhase('form');
  };

  const submit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.sensors.create({
        name: name.trim(),
        kind: kind === 'local' ? 'agent' : kind,
        coveredUrl: coveredUrl.trim(),
        coveredApp: coveredApp.trim(),
        basePath: basePath.trim() || '/',
        generationMode: genMode,
        realismLevel: realism,
      });
      setCreated(res);
      setPhase('created');
      onCreated();
      api.sensors.install(res.id).then(setInstall).catch(() => {});
    } catch {
      setError('No se pudo crear el sensor. Revisa el nombre e inténtalo de nuevo.');
    } finally {
      setSubmitting(false);
    }
  };

  // Espera del primer check-in: polling + señal del WebSocket.
  useEffect(() => {
    if (phase !== 'created' || !created || connected) return;
    let active = true;
    const check = () =>
      api.sensors.get(created.id)
        .then(s => { if (active && s.status === 'online') setConnected(true); })
        .catch(() => {});
    check();
    const t = setInterval(check, 3000);
    return () => { active = false; clearInterval(t); };
  }, [phase, created, connected, liveSignal]);

  const makeBundles = () => {
    if (!created) return;
    setGenning(true);
    api.sensors.generateBundles(created.id, 3)
      .then(setBundles)
      .catch(() => {})
      .finally(() => setGenning(false));
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg w-full max-w-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="font-medium">Añadir sensor</h3>
          <button onClick={onClose} className="text-fg-muted hover:text-fg"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5">
          {phase === 'questions' && (
            <div>
              <p className="text-sm text-fg-muted mb-3">Responde tres preguntas y te recomendamos el tipo de sensor.</p>
              <div className="divide-y divide-border/60">
                <YesNo label="¿Puedes instalar software en el host?" value={canInstall} onChange={setCanInstall} />
                <YesNo label="¿Necesitas detección de reuso de credenciales / retos CTF?" value={credReuse} onChange={setCredReuse} />
                <YesNo label="¿Importa el sigilo (no dejar rastro en el host)?" value={stealth} onChange={setStealth} />
              </div>
              {rec && (
                <div className="mt-4 bg-accent-soft border border-accent/30 rounded-lg p-4">
                  <div className="flex items-center gap-2 text-sm font-medium text-accent mb-1">
                    {(() => { const Icon = KIND_META[rec.kind].icon; return <Icon className="w-4 h-4" />; })()}
                    Recomendado: {KIND_META[rec.kind].label} <span className="font-mono text-xs text-fg-muted">({rec.kind})</span>
                  </div>
                  <p className="text-xs text-fg-muted">{rec.reason}</p>
                </div>
              )}
              <div className="mt-5 flex justify-end">
                <button
                  onClick={goForm}
                  disabled={!rec}
                  className="flex items-center gap-2 px-4 py-2 bg-accent text-bg rounded text-sm font-medium hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Continuar <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {phase === 'form' && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-fg-muted mb-1">Nombre</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
                  placeholder="prod-api-edge-01"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs text-fg-muted mb-1">Tipo de sensor</label>
                <div className="grid grid-cols-2 gap-2">
                  {(['agent', 'agentless'] as const).map(k => {
                    const Icon = KIND_META[k].icon;
                    return (
                      <button
                        key={k}
                        onClick={() => setKind(k)}
                        className={`flex items-center gap-2 px-3 py-2 rounded border text-sm transition-colors ${
                          kind === k ? 'border-accent bg-accent/10 text-accent' : 'border-border bg-surface-alt text-fg-muted hover:text-fg'
                        }`}
                      >
                        <Icon className="w-4 h-4" /> {KIND_META[k].label}
                        {rec?.kind === k && <span className="ml-auto text-[10px] font-mono">sugerido</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-fg-muted mb-1">URL cubierta</label>
                  <input
                    value={coveredUrl}
                    onChange={e => setCoveredUrl(e.target.value)}
                    className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
                    placeholder="https://api.ejemplo.com"
                  />
                </div>
                <div>
                  <label className="block text-xs text-fg-muted mb-1">Base path</label>
                  <input
                    value={basePath}
                    onChange={e => setBasePath(e.target.value)}
                    className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent font-mono"
                    placeholder="/"
                  />
                </div>
                <div>
                  <label className="block text-xs text-fg-muted mb-1">App cubierta (opcional)</label>
                  <input
                    value={coveredApp}
                    onChange={e => setCoveredApp(e.target.value)}
                    className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
                    placeholder="portal-clientes"
                  />
                </div>
                <div>
                  <label className="block text-xs text-fg-muted mb-1">Modo de generación</label>
                  <select
                    value={genMode}
                    onChange={e => setGenMode(e.target.value)}
                    className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
                  >
                    {GEN_MODES.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-fg-muted mb-1">Nivel de realismo: {realism}</label>
                  <input
                    type="range"
                    min={1}
                    max={5}
                    value={realism}
                    onChange={e => setRealism(Number(e.target.value))}
                    className="w-full accent-accent"
                  />
                </div>
              </div>
              {error && <p className="text-xs text-red">{error}</p>}
              <div className="flex justify-between pt-1">
                <button onClick={() => setPhase('questions')} className="px-4 py-2 bg-surface-alt rounded text-sm text-fg-muted hover:text-fg">Atrás</button>
                <button
                  onClick={submit}
                  disabled={submitting || !name.trim()}
                  className="flex items-center gap-2 px-4 py-2 bg-accent text-bg rounded text-sm font-medium hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Crear sensor
                </button>
              </div>
            </div>
          )}

          {phase === 'created' && created && (
            <div className="space-y-4">
              <div className="flex items-start gap-2 bg-amber/10 border border-amber/30 rounded-lg p-3">
                <AlertTriangle className="w-4 h-4 text-amber shrink-0 mt-0.5" />
                <p className="text-xs text-amber">
                  El secreto de API y el comando de instalación se muestran <strong>una sola vez</strong>. Cópialos ahora: no podrás volver a verlos.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-fg-muted mb-1">Key ID</div>
                  <div className="flex items-center gap-2">
                    <code className="font-mono text-xs break-all">{created.keyId}</code>
                    <CopyButton text={created.keyId} />
                  </div>
                </div>
                <div>
                  <div className="text-xs text-fg-muted mb-1">API secret</div>
                  <div className="flex items-center gap-2">
                    <code className="font-mono text-xs break-all">{created.apiSecret}</code>
                    <CopyButton text={created.apiSecret} />
                  </div>
                </div>
              </div>

              <CommandBlock title="Comando de instalación (un solo uso)" command={created.installCommand} />
              {install?.inspectCommand && (
                <CommandBlock title="Prefieres inspeccionar antes de ejecutar" command={install.inspectCommand} />
              )}

              {kind === 'agentless' && install?.agentless && (
                <div className="space-y-3 border-t border-border pt-4">
                  <div className="text-xs font-medium text-fg-muted uppercase tracking-wider">Instalación sin agente</div>
                  <ol className="space-y-1.5 list-decimal list-inside text-xs text-fg">
                    {install.agentless.steps.map((s, i) => <li key={i}>{s}</li>)}
                  </ol>
                  <CommandBlock title="Tarea cron (envío de logs)" command={install.agentless.cron} />
                  {install.agentless.note && <p className="text-[11px] text-fg-muted">{install.agentless.note}</p>}
                  <div className="flex flex-wrap items-center gap-2">
                    <a
                      href={downloads.shipper(created.id)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-blue/10 text-blue hover:bg-blue/20"
                    >
                      <Download className="w-3.5 h-3.5" /> Script de envío
                    </a>
                    <button
                      onClick={makeBundles}
                      disabled={genning}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-40"
                    >
                      {genning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Package className="w-3.5 h-3.5" />} Generar bundles
                    </button>
                  </div>
                  {bundles.length > 0 && (
                    <div className="space-y-1">
                      {bundles.map(b => (
                        <a
                          key={b.id}
                          href={downloads.bundle(b.filename)}
                          className="flex items-center gap-2 text-xs font-mono text-accent hover:underline"
                        >
                          <Download className="w-3.5 h-3.5" /> {b.filename}
                          <span className="text-fg-muted">({b.archiveFormat})</span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className={`flex items-center gap-2 rounded-lg p-3 border ${connected ? 'bg-green/10 border-green/30' : 'bg-surface-alt border-border'}`}>
                {connected
                  ? <><CheckCircle2 className="w-4 h-4 text-green" /><span className="text-sm text-green font-medium">Conectado</span></>
                  : <><Loader2 className="w-4 h-4 text-fg-muted animate-spin" /><span className="text-sm text-fg-muted">Esperando el primer check-in…</span></>}
              </div>

              <div className="flex justify-end">
                <button onClick={onClose} className="px-4 py-2 bg-accent text-bg rounded text-sm font-medium hover:bg-accent/90">
                  {connected ? 'Listo' : 'Cerrar'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ------- Página -------

export function Sensors() {
  const [sensors, setSensors] = useState<SensorDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizard, setWizard] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [liveSignal, setLiveSignal] = useState(0);

  const load = useCallback(() => {
    api.sensors.list().then(setSensors).catch(() => {}).finally(() => setLoading(false));
  }, []);

  // Carga inicial + refresco cada 5s.
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  // Re-fetch ante eventos del WebSocket (con debounce) + señal para el asistente.
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    const unsub = connectLive(() => {
      setLiveSignal(s => s + 1);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(load, 400);
    });
    return () => {
      unsub();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const toggleEnabled = async (s: SensorDto) => {
    setBusy(s.id);
    try {
      if (s.enabled) await api.sensors.disable(s.id);
      else await api.sensors.enable(s.id);
      load();
    } finally { setBusy(null); }
  };

  const rotateSeed = async (s: SensorDto) => {
    setBusy(s.id);
    try { await api.sensors.rotateSeed(s.id); load(); }
    finally { setBusy(null); }
  };

  const decommission = async (s: SensorDto) => {
    if (!window.confirm(`¿Dar de baja el sensor "${s.name}"? Se revocan sus credenciales y dejará de ingerir.`)) return;
    setBusy(s.id);
    try { await api.sensors.remove(s.id); load(); }
    finally { setBusy(null); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Sensores</h1>
          <p className="text-sm text-fg-muted mt-1">Sensores desplegados (agente / sin agente) que alimentan la detección</p>
        </div>
        <button
          onClick={() => setWizard(true)}
          className="flex items-center gap-2 px-3 py-2 bg-accent text-bg rounded-md text-sm font-medium hover:bg-accent/90 transition-colors"
        >
          <Plus className="w-4 h-4" /> Añadir sensor
        </button>
      </div>

      <div className="bg-surface rounded-lg border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-medium text-fg-muted uppercase tracking-wider">
                <th className="text-left px-4 py-3">Sensor</th>
                <th className="text-left px-4 py-3">Tipo</th>
                <th className="text-left px-4 py-3">Cobertura</th>
                <th className="text-left px-4 py-3">Estado</th>
                <th className="text-left px-4 py-3">Activo</th>
                <th className="text-left px-4 py-3">Ses. / Alertas</th>
                <th className="text-left px-4 py-3">Versión</th>
                <th className="text-left px-4 py-3">Último check-in</th>
                <th className="text-right px-4 py-3">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {sensors.map(s => {
                const st = STATUS[s.status] ?? STATUS.unknown;
                const KindIcon = KIND_META[s.kind].icon;
                const working = busy === s.id;
                return (
                  <tr key={s.id} className="border-b border-border/50 hover:bg-surface-alt/40 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-medium">{s.name}</div>
                      <div className="text-[10px] font-mono text-fg-muted">seed {s.seed.slice(0, 8)}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
                        <KindIcon className="w-3.5 h-3.5" /> {KIND_META[s.kind].label}
                      </span>
                    </td>
                    <td className="px-4 py-3 max-w-[200px]">
                      <div className="text-xs truncate" title={s.coveredUrl || s.coveredApp || ''}>
                        {s.coveredUrl || s.coveredApp || '—'}
                      </div>
                      <div className="text-[10px] font-mono text-fg-muted truncate">{s.basePath}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5 text-xs">
                        <span className={`w-2.5 h-2.5 rounded-full ${st.dot}`} />
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleEnabled(s)}
                        disabled={working || s.kind === 'local'}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-40 ${s.enabled ? 'bg-green/70' : 'bg-surface-alt'}`}
                        title={s.enabled ? 'Deshabilitar' : 'Habilitar'}
                      >
                        <span className={`inline-block h-3.5 w-3.5 rounded-full bg-fg transition-transform ${s.enabled ? 'translate-x-4' : 'translate-x-1'}`} />
                      </button>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      <span className="text-fg">{s.sessionCount}</span>
                      <span className="text-fg-muted"> / </span>
                      <span className={s.alertCount > 0 ? 'text-red' : 'text-fg-muted'}>{s.alertCount}</span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-fg-muted">
                      {s.agentVersion ? `v${s.agentVersion}` : '—'}
                      <span className="block">cfg {s.configVersion}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-muted" title={s.lastSeen ?? ''}>{relTime(s.lastSeen)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => toggleEnabled(s)}
                          disabled={working || s.kind === 'local'}
                          className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium disabled:opacity-40 ${
                            s.enabled ? 'bg-red/10 text-red hover:bg-red/20' : 'bg-green/10 text-green hover:bg-green/20'
                          }`}
                          title={s.enabled ? 'Deshabilitar' : 'Habilitar'}
                        >
                          <Power className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => rotateSeed(s)}
                          disabled={working}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-blue/10 text-blue hover:bg-blue/20 disabled:opacity-40"
                          title="Rotar seed"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => decommission(s)}
                          disabled={working || s.kind === 'local'}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-surface-alt text-fg-muted hover:text-red hover:bg-red/10 disabled:opacity-40"
                          title="Dar de baja"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {sensors.length === 0 && !loading && (
                <tr><td colSpan={9} className="px-4 py-10 text-center text-fg-muted text-sm">
                  No hay sensores. Usa <span className="text-accent">Añadir sensor</span> para desplegar el primero.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {wizard && (
        <AddSensorWizard
          liveSignal={liveSignal}
          onClose={() => setWizard(false)}
          onCreated={load}
        />
      )}
    </div>
  );
}

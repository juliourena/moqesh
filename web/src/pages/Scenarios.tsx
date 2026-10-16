import { useEffect, useState } from 'react';
import { Play, Download, Upload, Trash2, Plus, Pencil, X, Lock, EyeOff, KeyRound } from 'lucide-react';
import { api } from '../services/api';
import type { ScenarioSummary, ScenarioDetail, ScenarioNode, ScenarioCredential } from '../types';

const KINDS = ['page', 'dir', 'file', 'binary', 'api', 'login', 'vault', 'flag'];
const VIS = ['linked', 'hidden'];
const CREDKINDS = ['bearer', 'basic', 'apikey', 'dbconn', 'ssh'];

function Field({ label, value, onChange, textarea, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; textarea?: boolean; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] text-fg-muted mb-0.5">{label}</span>
      {textarea ? (
        <textarea value={value} onChange={e => onChange(e.target.value)} rows={4} placeholder={placeholder}
          className="w-full bg-surface-alt border border-border rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-accent" />
      ) : (
        <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
          className="w-full bg-surface-alt border border-border rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-accent" />
      )}
    </label>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[]; }) {
  return (
    <label className="block">
      <span className="block text-[11px] text-fg-muted mb-0.5">{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full bg-surface-alt border border-border rounded px-2 py-1 text-xs focus:outline-none focus:border-accent">
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

export function Scenarios() {
  const [list, setList] = useState<ScenarioSummary[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [importText, setImportText] = useState('');
  const [editNode, setEditNode] = useState<Partial<ScenarioNode> | null>(null);
  const [editCred, setEditCred] = useState<Partial<ScenarioCredential> | null>(null);
  const [builtins, setBuiltins] = useState<string[]>([]);

  const loadList = () => api.scenarios.list().then(l => { setList(l); if (sel == null && l.length) setSel(l.find(s => s.isActive)?.id ?? l[0].id); }).catch(() => {});
  const loadDetail = (id: number) => api.scenarios.get(id).then(setDetail).catch(() => setDetail(null));

  useEffect(() => { loadList(); api.scenarios.builtins().then(setBuiltins).catch(() => {}); }, []);
  useEffect(() => { if (sel != null) loadDetail(sel); }, [sel]);

  const refresh = () => { loadList(); if (sel != null) loadDetail(sel); };

  const doImport = async () => {
    try {
      const pack = JSON.parse(importText);
      const r = await api.scenarios.import(pack, true);
      setImportText(''); setSel(r.id); loadList();
    } catch (e) { alert('JSON inválido: ' + (e as Error).message); }
  };

  const saveNode = async () => {
    if (!editNode || sel == null) return;
    if (editNode.id) await api.scenarios.updateNode(editNode.id, editNode);
    else await api.scenarios.addNode(sel, editNode);
    setEditNode(null); refresh();
  };
  const saveCred = async () => {
    if (!editCred || sel == null) return;
    if (editCred.id) await api.scenarios.updateCred(editCred.id, editCred);
    else await api.scenarios.addCred(sel, editCred);
    setEditCred(null); refresh();
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Escenarios CTF</h1>
        <p className="text-sm text-fg-muted mt-1">Cadenas de ataque maleables: rutas ocultas, credenciales usables, binarios decompilables, vaults.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Lista de packs */}
        <div className="lg:col-span-1 space-y-3">
          <div className="bg-surface border border-border rounded-lg p-3 space-y-1.5">
            {list.map(s => (
              <button key={s.id} onClick={() => setSel(s.id)}
                className={`w-full text-left px-2.5 py-2 rounded-md text-sm transition-colors ${sel === s.id ? 'bg-accent/15 text-accent' : 'hover:bg-surface-alt'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-medium">{s.name}</span>
                  {s.isActive && <span className="w-2 h-2 rounded-full bg-green" title="activo" />}
                </div>
                <div className="text-[11px] text-fg-muted">{s.nodeCount} nodos · {s.credCount} creds</div>
              </button>
            ))}
            {list.length === 0 && <p className="text-xs text-fg-muted text-center py-3">Sin escenarios</p>}
          </div>

          <div className="bg-surface border border-border rounded-lg p-3">
            <div className="text-xs font-medium mb-2 flex items-center gap-1.5"><Upload className="w-3.5 h-3.5" /> Importar pack JSON</div>
            <textarea value={importText} onChange={e => setImportText(e.target.value)} rows={5} placeholder='{"name":"...","nodes":[...],"credentials":[...]}'
              className="w-full bg-surface-alt border border-border rounded px-2 py-1 text-[11px] font-mono focus:outline-none focus:border-accent" />
            <button onClick={doImport} disabled={!importText.trim()}
              className="mt-2 w-full px-3 py-1.5 bg-accent text-bg rounded text-xs font-medium hover:bg-accent/90 disabled:opacity-40">Importar y activar</button>
            {builtins.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border">
                <div className="text-[11px] text-fg-muted mb-1.5">Plantillas incorporadas</div>
                <div className="flex flex-wrap gap-1.5">
                  {builtins.map(b => (
                    <button key={b} onClick={() => api.scenarios.importBuiltin(b, false).then(() => loadList())}
                      className="px-2 py-1 bg-surface-alt border border-border rounded text-[11px] font-mono hover:border-accent hover:text-accent">+ {b}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Detalle */}
        <div className="lg:col-span-3 space-y-4">
          {detail && (
            <>
              <div className="bg-surface border border-border rounded-lg p-4 flex items-center justify-between">
                <div>
                  <h2 className="font-semibold">{detail.scenario.name} {detail.scenario.isActive && <span className="text-[10px] text-green border border-green/40 rounded px-1.5 py-0.5 ml-2">ACTIVO</span>}</h2>
                  <p className="text-xs text-fg-muted mt-0.5">{detail.scenario.description}</p>
                </div>
                <div className="flex gap-2">
                  {!detail.scenario.isActive && (
                    <button onClick={() => api.scenarios.activate(detail.scenario.id).then(refresh)}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-green/10 text-green hover:bg-green/20"><Play className="w-3 h-3" /> Activar</button>
                  )}
                  <a href={api.scenarios.exportUrl(detail.scenario.id)} download={`${detail.scenario.name}.json`}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-blue/10 text-blue hover:bg-blue/20"><Download className="w-3 h-3" /> Exportar</a>
                  <button onClick={() => { if (confirm('¿Eliminar escenario?')) api.scenarios.delete(detail.scenario.id).then(() => { setSel(null); setDetail(null); loadList(); }); }}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-surface-alt text-fg-muted hover:text-red hover:bg-red/10"><Trash2 className="w-3 h-3" /></button>
                </div>
              </div>

              {/* Cadena de nodos */}
              <div className="bg-surface border border-border rounded-lg overflow-hidden">
                <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                  <h3 className="text-sm font-medium">Cadena de ataque ({detail.nodes.length} nodos)</h3>
                  <button onClick={() => setEditNode({ path: '/', visibility: 'linked', kind: 'file', stage: 0, binaryKind: 'none' })}
                    className="flex items-center gap-1 text-xs text-accent hover:underline"><Plus className="w-3 h-3" /> Nodo</button>
                </div>
                <div className="divide-y divide-border/50">
                  {detail.nodes.map(n => (
                    <div key={n.id} className="px-4 py-2.5 flex items-start justify-between gap-3 hover:bg-surface-alt/40">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[10px] font-mono bg-surface-alt px-1 rounded text-fg-muted">#{n.stage}</span>
                          <span className="font-mono text-xs truncate">{n.path}</span>
                          <span className="text-[10px] font-mono px-1 rounded bg-surface-alt text-fg-muted">{n.kind}</span>
                          {n.visibility === 'hidden' && <span className="text-[10px] text-amber flex items-center gap-0.5"><EyeOff className="w-3 h-3" />oculto</span>}
                          {n.requiresCredentialKey && <span className="text-[10px] text-red flex items-center gap-0.5"><Lock className="w-3 h-3" />{n.requiresCredentialKey}</span>}
                          {n.binaryKind !== 'none' && <span className="text-[10px] text-blue">{n.binaryKind}</span>}
                        </div>
                        <div className="text-[10px] text-fg-muted mt-0.5 flex gap-3 flex-wrap">
                          {n.grantsCredentialKeys && <span>otorga: {n.grantsCredentialKeys}</span>}
                          {n.hintedByPaths && <span>pista en: {n.hintedByPaths}</span>}
                        </div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button onClick={() => setEditNode(n)} className="text-fg-muted hover:text-accent"><Pencil className="w-3.5 h-3.5" /></button>
                        <button onClick={() => { if (confirm('¿Eliminar nodo?')) api.scenarios.deleteNode(n.id).then(refresh); }} className="text-fg-muted hover:text-red"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Credenciales */}
              <div className="bg-surface border border-border rounded-lg overflow-hidden">
                <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                  <h3 className="text-sm font-medium flex items-center gap-1.5"><KeyRound className="w-4 h-4" /> Credenciales ({detail.credentials.length})</h3>
                  <button onClick={() => setEditCred({ key: '', kind: 'bearer' })} className="flex items-center gap-1 text-xs text-accent hover:underline"><Plus className="w-3 h-3" /> Credencial</button>
                </div>
                <div className="divide-y divide-border/50">
                  {detail.credentials.map(c => (
                    <div key={c.id} className="px-4 py-2 flex items-center justify-between gap-3 hover:bg-surface-alt/40 text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-accent">{c.key}</span>
                        <span className="text-[10px] px-1 rounded bg-surface-alt text-fg-muted">{c.kind}</span>
                        {c.username && <span className="text-fg-muted">user: {c.username}</span>}
                        <span className="text-fg-muted">{c.secret ? 'secreto fijo' : 'secreto por seed'}</span>
                        {c.foundInPath && <span className="text-fg-muted">en {c.foundInPath}</span>}
                        {c.usableAtPath && <span className="text-fg-muted">→ {c.usableAtPath}</span>}
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button onClick={() => setEditCred(c)} className="text-fg-muted hover:text-accent"><Pencil className="w-3.5 h-3.5" /></button>
                        <button onClick={() => { if (confirm('¿Eliminar credencial?')) api.scenarios.deleteCred(c.id).then(refresh); }} className="text-fg-muted hover:text-red"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Editor de nodo */}
      {editNode && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setEditNode(null)}>
          <div className="bg-surface border border-border rounded-lg p-5 w-full max-w-lg max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4"><h3 className="font-medium">{editNode.id ? 'Editar' : 'Nuevo'} nodo</h3><button onClick={() => setEditNode(null)}><X className="w-4 h-4 text-fg-muted" /></button></div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Path" value={editNode.path ?? ''} onChange={v => setEditNode({ ...editNode, path: v })} placeholder="/backup/Portal.dll" />
              <Field label="Stage" value={String(editNode.stage ?? 0)} onChange={v => setEditNode({ ...editNode, stage: Number(v) || 0 })} />
              <Select label="Visibility" value={editNode.visibility ?? 'linked'} onChange={v => setEditNode({ ...editNode, visibility: v })} options={VIS} />
              <Select label="Kind" value={editNode.kind ?? 'file'} onChange={v => setEditNode({ ...editNode, kind: v })} options={KINDS} />
              <Field label="Requires cred key (gate)" value={editNode.requiresCredentialKey ?? ''} onChange={v => setEditNode({ ...editNode, requiresCredentialKey: v || null })} placeholder="svc_bearer" />
              <Field label="Grants cred keys (csv)" value={editNode.grantsCredentialKeys ?? ''} onChange={v => setEditNode({ ...editNode, grantsCredentialKeys: v || null })} placeholder="admin,aws" />
              <Field label="Hinted by paths (csv)" value={editNode.hintedByPaths ?? ''} onChange={v => setEditNode({ ...editNode, hintedByPaths: v || null })} placeholder="/robots.txt" />
              <Select label="Binary kind" value={editNode.binaryKind ?? 'none'} onChange={v => setEditNode({ ...editNode, binaryKind: v })} options={['none', 'dotnetdll', 'elf']} />
            </div>
            <div className="mt-3"><Field label="Content-Type" value={editNode.contentType ?? ''} onChange={v => setEditNode({ ...editNode, contentType: v })} placeholder="text/html; charset=utf-8" /></div>
            <div className="mt-3"><Field label="Body template (placeholders: {{brand}} {{token}} {{cred:KEY}} {{user:KEY}})" value={editNode.bodyTemplate ?? ''} onChange={v => setEditNode({ ...editNode, bodyTemplate: v })} textarea /></div>
            {editNode.binaryKind !== 'none' && (
              <div className="mt-3"><Field label="Binary secret (connection=.. api=.. bearercred=KEY)" value={editNode.binarySecret ?? ''} onChange={v => setEditNode({ ...editNode, binarySecret: v })} textarea /></div>
            )}
            <div className="mt-4 flex gap-2"><button onClick={saveNode} className="px-4 py-2 bg-accent text-bg rounded text-sm font-medium">Guardar</button><button onClick={() => setEditNode(null)} className="px-4 py-2 bg-surface-alt rounded text-sm text-fg-muted">Cancelar</button></div>
          </div>
        </div>
      )}

      {/* Editor de credencial */}
      {editCred && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setEditCred(null)}>
          <div className="bg-surface border border-border rounded-lg p-5 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4"><h3 className="font-medium">{editCred.id ? 'Editar' : 'Nueva'} credencial</h3><button onClick={() => setEditCred(null)}><X className="w-4 h-4 text-fg-muted" /></button></div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Key" value={editCred.key ?? ''} onChange={v => setEditCred({ ...editCred, key: v })} placeholder="svc_bearer" />
              <Select label="Kind" value={editCred.kind ?? 'bearer'} onChange={v => setEditCred({ ...editCred, kind: v })} options={CREDKINDS} />
              <Field label="Username" value={editCred.username ?? ''} onChange={v => setEditCred({ ...editCred, username: v || null })} placeholder="admin" />
              <Field label="Secret (vacío = por seed)" value={editCred.secret ?? ''} onChange={v => setEditCred({ ...editCred, secret: v })} />
              <Field label="Found in path" value={editCred.foundInPath ?? ''} onChange={v => setEditCred({ ...editCred, foundInPath: v || null })} placeholder="/backup/Portal.dll" />
              <Field label="Usable at path" value={editCred.usableAtPath ?? ''} onChange={v => setEditCred({ ...editCred, usableAtPath: v || null })} placeholder="/admin/" />
            </div>
            <div className="mt-4 flex gap-2"><button onClick={saveCred} className="px-4 py-2 bg-accent text-bg rounded text-sm font-medium">Guardar</button><button onClick={() => setEditCred(null)} className="px-4 py-2 bg-surface-alt rounded text-sm text-fg-muted">Cancelar</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

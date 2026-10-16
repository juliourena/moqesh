import { useEffect, useState } from 'react';
import { Ban, Plus, RotateCcw } from 'lucide-react';
import { api } from '../services/api';
import type { BlockedIp } from '../types';

export function Blocks() {
  const [blocks, setBlocks] = useState<BlockedIp[]>([]);
  const [ip, setIp] = useState('');
  const [reason, setReason] = useState('');

  const load = () => api.blocks.list().then(setBlocks).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);

  const doBlock = async () => { if (!ip.trim()) return; await api.blocks.block(ip.trim(), reason || 'bloqueo manual'); setIp(''); setReason(''); load(); };

  const active = blocks.filter(b => b.active);
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Bloqueos</h1>
        <p className="text-sm text-fg-muted mt-1">IPs bloqueadas por el honeypot. Un atacante confirmado se bloquea y notifica automáticamente; el honeypot le responde 403.</p>
      </div>

      <div className="bg-surface border border-border rounded-lg p-4 mb-5">
        <div className="text-xs font-medium mb-2 flex items-center gap-1.5"><Plus className="w-3.5 h-3.5" /> Bloqueo manual</div>
        <div className="flex gap-2 flex-wrap">
          <input value={ip} onChange={e => setIp(e.target.value)} placeholder="IP (ej. 203.0.113.5)"
            className="bg-surface-alt border border-border rounded px-3 py-1.5 text-sm font-mono w-48 focus:outline-none focus:border-accent" />
          <input value={reason} onChange={e => setReason(e.target.value)} placeholder="motivo (opcional)"
            className="bg-surface-alt border border-border rounded px-3 py-1.5 text-sm flex-1 min-w-40 focus:outline-none focus:border-accent" />
          <button onClick={doBlock} className="flex items-center gap-1.5 px-3 py-1.5 bg-red/15 text-red rounded text-sm font-medium hover:bg-red/25"><Ban className="w-3.5 h-3.5" /> Bloquear</button>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border text-sm font-medium">Activos ({active.length})</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-fg-muted uppercase tracking-wider">
                <th className="text-left px-4 py-2 font-medium">IP</th>
                <th className="text-left px-4 py-2 font-medium">Origen</th>
                <th className="text-left px-4 py-2 font-medium">Motivo</th>
                <th className="text-left px-4 py-2 font-medium">Fecha</th>
                <th className="text-right px-4 py-2 font-medium">Acción</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map(b => (
                <tr key={b.id} className={`border-b border-border/50 ${b.active ? '' : 'opacity-40'}`}>
                  <td className="px-4 py-2 font-mono text-xs">{b.ip}</td>
                  <td className="px-4 py-2"><span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${b.source === 'auto' ? 'bg-red/15 text-red' : 'bg-surface-alt text-fg-muted'}`}>{b.source}</span></td>
                  <td className="px-4 py-2 text-xs text-fg-muted max-w-sm truncate" title={b.reason}>{b.reason}</td>
                  <td className="px-4 py-2 text-xs text-fg-muted">{new Date(b.createdAt).toLocaleString()}</td>
                  <td className="px-4 py-2 text-right">
                    {b.active && <button onClick={() => api.blocks.unblock(b.id).then(load)} className="flex items-center gap-1 text-xs text-fg-muted hover:text-accent ml-auto"><RotateCcw className="w-3 h-3" /> desbloquear</button>}
                  </td>
                </tr>
              ))}
              {blocks.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-fg-muted text-sm">Sin bloqueos</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

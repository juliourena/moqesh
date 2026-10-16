import { useEffect, useState } from 'react';
import { Plus, Power, Upload, Trash2, ExternalLink, Copy, Check } from 'lucide-react';
import { api } from '../services/api';
import type { HoneypotDto } from '../types';

export function Honeypots() {
  const [honeypots, setHoneypots] = useState<HoneypotDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState('HTTP');
  const [newPort, setNewPort] = useState(8080);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const honeypotUrl = (port: number) => {
    const host = window.location.hostname;
    return `http://${host}:${port}`;
  };

  const copyUrl = (id: number, port: number) => {
    navigator.clipboard.writeText(honeypotUrl(port)).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    }).catch(() => {});
  };

  const load = () => {
    api.honeypots.list()
      .then(setHoneypots)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await api.honeypots.create({ name: newName, type: newType, port: newPort });
    setShowCreate(false);
    setNewName('');
    load();
  };

  const handleToggle = async (id: number) => {
    await api.honeypots.toggle(id);
    load();
  };

  const handleDelete = async (id: number) => {
    await api.honeypots.delete(id);
    load();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Honeypots</h1>
          <p className="text-sm text-fg-muted mt-1">Gestión de servicios honeypot</p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 px-3 py-2 bg-accent text-bg rounded-md text-sm font-medium hover:bg-accent/90 transition-colors"
        >
          <Plus className="w-4 h-4" /> Nuevo honeypot
        </button>
      </div>

      {showCreate && (
        <div className="bg-surface border border-border rounded-lg p-5 mb-6">
          <h3 className="text-sm font-medium mb-4">Crear honeypot</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-fg-muted mb-1">Nombre</label>
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
                placeholder="Mi honeypot"
              />
            </div>
            <div>
              <label className="block text-xs text-fg-muted mb-1">Tipo</label>
              <select
                value={newType}
                onChange={e => setNewType(e.target.value)}
                className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
              >
                <option value="HTTP">HTTP</option>
                <option value="SSH">SSH</option>
                <option value="API">REST API</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-fg-muted mb-1">Puerto</label>
              <input
                type="number"
                value={newPort}
                onChange={e => setNewPort(Number(e.target.value))}
                className="w-full bg-surface-alt border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
              />
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={handleCreate} className="px-4 py-2 bg-accent text-bg rounded text-sm font-medium hover:bg-accent/90">Crear</button>
            <button onClick={() => setShowCreate(false)} className="px-4 py-2 bg-surface-alt rounded text-sm text-fg-muted hover:text-fg">Cancelar</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {honeypots.map(hp => (
          <div key={hp.id} className="bg-surface border border-border rounded-lg p-5">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="font-medium">{hp.name}</h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs font-mono text-fg-muted bg-surface-alt px-1.5 py-0.5 rounded">{hp.type}</span>
                  <span className="text-xs font-mono text-fg-muted">:{hp.port}</span>
                </div>
              </div>
              <span className={`w-2.5 h-2.5 rounded-full ${hp.isActive ? 'bg-green' : 'bg-fg-muted'}`} />
            </div>
            {hp.isActive && hp.type === 'HTTP' && (
              <div className="flex items-center gap-1.5 mt-2 mb-1">
                <a
                  href={honeypotUrl(hp.port)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-mono text-accent hover:underline truncate"
                >
                  {honeypotUrl(hp.port)}
                </a>
                <a
                  href={honeypotUrl(hp.port)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-fg-muted hover:text-accent shrink-0"
                >
                  <ExternalLink className="w-3 h-3" />
                </a>
                <button
                  onClick={() => copyUrl(hp.id, hp.port)}
                  className="text-fg-muted hover:text-accent shrink-0"
                  title="Copiar URL"
                >
                  {copiedId === hp.id ? <Check className="w-3 h-3 text-green" /> : <Copy className="w-3 h-3" />}
                </button>
              </div>
            )}
            <p className="text-xs text-fg-muted mb-4">{hp.requestCount} requests registrados</p>
            <div className="flex gap-2">
              <button
                onClick={() => handleToggle(hp.id)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors ${
                  hp.isActive ? 'bg-red/10 text-red hover:bg-red/20' : 'bg-green/10 text-green hover:bg-green/20'
                }`}
              >
                <Power className="w-3 h-3" /> {hp.isActive ? 'Detener' : 'Activar'}
              </button>
              <button className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-blue/10 text-blue hover:bg-blue/20">
                <Upload className="w-3 h-3" /> Upload
              </button>
              <button
                onClick={() => handleDelete(hp.id)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium bg-surface-alt text-fg-muted hover:text-red hover:bg-red/10"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
        {honeypots.length === 0 && !loading && (
          <div className="col-span-full text-center py-12 text-fg-muted">
            <p className="text-sm">No hay honeypots configurados</p>
            <p className="text-xs mt-1">Crea uno para empezar a monitorear</p>
          </div>
        )}
      </div>
    </div>
  );
}

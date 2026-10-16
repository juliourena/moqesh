import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { RequestLogDto } from '../types';

export function Requests() {
  const [requests, setRequests] = useState<RequestLogDto[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.requests.list({ limit: 100 })
      .then(setRequests)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Requests</h1>
        <p className="text-sm text-fg-muted mt-1">Todas las interacciones con los honeypots</p>
      </div>

      <div className="bg-surface rounded-lg border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">Timestamp</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">IP</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">Method</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">Path</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-fg-muted uppercase tracking-wider">Time</th>
              </tr>
            </thead>
            <tbody>
              {requests.map(req => (
                <tr key={req.id} className="border-b border-border/50 hover:bg-surface-alt/50 transition-colors">
                  <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{new Date(req.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{req.sourceIp}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${
                      req.method === 'GET' ? 'bg-green/10 text-green' :
                      req.method === 'POST' ? 'bg-blue/10 text-blue' :
                      'bg-amber/10 text-amber'
                    }`}>{req.method}</span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs max-w-xs truncate">{req.path}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-mono ${
                      req.responseCode < 300 ? 'text-green' :
                      req.responseCode < 400 ? 'text-amber' :
                      'text-red'
                    }`}>{req.responseCode}</span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{req.processingTimeMs.toFixed(1)}ms</td>
                </tr>
              ))}
              {requests.length === 0 && !loading && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-fg-muted text-sm">Sin requests registrados</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

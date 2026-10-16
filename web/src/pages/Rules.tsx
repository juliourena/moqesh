import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { DetectionRule } from '../types';

export function Rules() {
  const [rules, setRules] = useState<DetectionRule[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.rules.list()
      .then(setRules)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleToggle = async (rule: DetectionRule) => {
    await api.rules.update(rule.id, { isActive: !rule.isActive });
    load();
  };

  const handleWeightChange = async (rule: DetectionRule, weight: number) => {
    await api.rules.update(rule.id, { weight });
    load();
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Detection Rules</h1>
        <p className="text-sm text-fg-muted mt-1">Reglas de detección de AI agents con scoring ponderado</p>
      </div>

      <div className="space-y-3">
        {rules.map(rule => (
          <div key={rule.id} className={`bg-surface border border-border rounded-lg p-5 transition-opacity ${rule.isActive ? '' : 'opacity-50'}`}>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap">
                  <h3 className="font-medium">{rule.name}</h3>
                  <span className="text-xs font-mono text-fg-muted bg-surface-alt px-1.5 py-0.5 rounded">{rule.ruleType}</span>
                </div>
                <p className="text-sm text-fg-muted mt-1">{rule.description}</p>
              </div>
              <div className="flex items-center gap-4 shrink-0">
                <div className="text-right">
                  <label className="block text-[10px] text-fg-muted uppercase tracking-wider mb-1">Weight</label>
                  <input
                    type="number"
                    min="0" max="1" step="0.05"
                    value={rule.weight}
                    onChange={e => handleWeightChange(rule, Number(e.target.value))}
                    className="w-16 bg-surface-alt border border-border rounded px-2 py-1 text-sm font-mono text-center focus:outline-none focus:border-accent"
                  />
                </div>
                <button
                  onClick={() => handleToggle(rule)}
                  className={`w-10 h-5 rounded-full transition-colors relative ${rule.isActive ? 'bg-accent' : 'bg-surface-alt'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${rule.isActive ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
            </div>
          </div>
        ))}
        {rules.length === 0 && !loading && (
          <div className="text-center py-12 text-fg-muted">
            <p className="text-sm">Sin reglas configuradas</p>
          </div>
        )}
      </div>
    </div>
  );
}

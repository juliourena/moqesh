import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import type { TimeSeriesPoint } from '../../types';

interface Props {
  data: TimeSeriesPoint[];
}

export function RequestsChart({ data }: Props) {
  const formatted = data.map(d => ({
    ...d,
    label: new Date(d.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  }));

  return (
    <div className="bg-surface rounded-lg border border-border p-5">
      <h3 className="text-sm font-medium text-fg-muted mb-4">Requests — últimas 24h</h3>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={formatted}>
            <defs>
              <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#e8a838" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#e8a838" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a3040" />
            <XAxis dataKey="label" tick={{ fill: '#8892a8', fontSize: 11 }} axisLine={{ stroke: '#2a3040' }} tickLine={false} />
            <YAxis tick={{ fill: '#8892a8', fontSize: 11 }} axisLine={false} tickLine={false} width={35} />
            <Tooltip
              contentStyle={{ background: '#1e2436', border: '1px solid #2a3040', borderRadius: 6, fontSize: 13 }}
              labelStyle={{ color: '#8892a8' }}
            />
            <Area type="monotone" dataKey="count" stroke="#e8a838" strokeWidth={2} fill="url(#reqGrad)" name="Requests" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

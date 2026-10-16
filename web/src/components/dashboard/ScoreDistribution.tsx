import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import type { ScoreDistributionPoint } from '../../types';

interface Props {
  data: ScoreDistributionPoint[];
}

const colors = ['#4ade80', '#a3e635', '#fbbf24', '#fb923c', '#f87171'];

export function ScoreDistribution({ data }: Props) {
  return (
    <div className="bg-surface rounded-lg border border-border p-5">
      <h3 className="text-sm font-medium text-fg-muted mb-4">AI Score Distribution</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <XAxis dataKey="range" tick={{ fill: '#8892a8', fontSize: 10 }} axisLine={{ stroke: '#2a3040' }} tickLine={false} />
            <YAxis tick={{ fill: '#8892a8', fontSize: 11 }} axisLine={false} tickLine={false} width={30} />
            <Tooltip
              contentStyle={{ background: '#1e2436', border: '1px solid #2a3040', borderRadius: 6, fontSize: 13 }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} name="Sessions">
              {data.map((_, i) => (
                <Cell key={i} fill={colors[i] || '#e8a838'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

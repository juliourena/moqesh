import { type LucideIcon } from 'lucide-react';

interface Props {
  title: string;
  value: number | string;
  icon: LucideIcon;
  color: 'accent' | 'blue' | 'green' | 'red';
  subtitle?: string;
}

const colorMap = {
  accent: 'text-accent bg-accent/10',
  blue: 'text-blue bg-blue/10',
  green: 'text-green bg-green/10',
  red: 'text-red bg-red/10',
};

export function KpiCard({ title, value, icon: Icon, color, subtitle }: Props) {
  return (
    <div className="bg-surface rounded-lg border border-border p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-fg-muted uppercase tracking-wider">{title}</p>
          <p className="text-3xl font-semibold mt-1 font-mono tabular-nums">{value}</p>
          {subtitle && <p className="text-xs text-fg-muted mt-1">{subtitle}</p>}
        </div>
        <div className={`p-2 rounded-md ${colorMap[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { Activity, Users, Bot, Bell } from 'lucide-react';
import { KpiCard } from '../components/dashboard/KpiCard';
import { RequestsChart } from '../components/dashboard/RequestsChart';
import { ScoreDistribution } from '../components/dashboard/ScoreDistribution';
import { TopSources } from '../components/dashboard/TopSources';
import { RecentAlerts } from '../components/dashboard/RecentAlerts';
import { api } from '../services/api';
import { connectLive } from '../services/realtime';
import type { DashboardOverview } from '../types';

const mockData: DashboardOverview = {
  totalRequests: 2847,
  activeSessions: 47,
  aiAgentsDetected: 12,
  unresolvedAlerts: 3,
  requestsOverTime: Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(Date.now() - (23 - i) * 3600000).toISOString(),
    count: Math.floor(Math.random() * 200 + 50 + Math.sin(i / 3) * 80),
  })),
  scoreDistribution: [
    { range: '0.0-0.2', count: 156 },
    { range: '0.2-0.4', count: 89 },
    { range: '0.4-0.6', count: 34 },
    { range: '0.6-0.8', count: 18 },
    { range: '0.8-1.0', count: 7 },
  ],
  topSources: [
    { ip: '45.33.32.156', requestCount: 347, maxScore: 0.92 },
    { ip: '192.168.1.105', requestCount: 213, maxScore: 0.78 },
    { ip: '10.0.4.22', requestCount: 189, maxScore: 0.45 },
    { ip: '172.16.0.88', requestCount: 156, maxScore: 0.85 },
    { ip: '203.0.113.42', requestCount: 134, maxScore: 0.31 },
    { ip: '198.51.100.7', requestCount: 98, maxScore: 0.67 },
  ],
  recentAlerts: [
    { id: 1, severity: 'Critical', title: 'AI agent detected: sequential binary download + execution from 45.33.32.156', createdAt: new Date(Date.now() - 300000).toISOString(), acknowledged: false },
    { id: 2, severity: 'High', title: 'Token exhaust chain triggered: 47 requests deep from 172.16.0.88', createdAt: new Date(Date.now() - 1800000).toISOString(), acknowledged: false },
    { id: 3, severity: 'Medium', title: 'Honeytoken AWS key accessed from 192.168.1.105', createdAt: new Date(Date.now() - 3600000).toISOString(), acknowledged: true },
    { id: 4, severity: 'High', title: 'README literal execution pattern detected from 198.51.100.7', createdAt: new Date(Date.now() - 7200000).toISOString(), acknowledged: false },
    { id: 5, severity: 'Low', title: 'New session with suspicious User-Agent header', createdAt: new Date(Date.now() - 14400000).toISOString(), acknowledged: true },
  ],
};

export function Dashboard() {
  const [data, setData] = useState<DashboardOverview>(mockData);

  useEffect(() => {
    const refresh = () => api.dashboard.overview().then(setData).catch(() => setData(mockData));
    refresh();
    // Tiempo real: refresca (con debounce) ante cada request/alerta del honeypot.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsub = connectLive(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(refresh, 400);
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-fg-muted mt-1">Monitoreo de actividad en honeypots</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KpiCard title="Total Requests" value={data.totalRequests.toLocaleString()} icon={Activity} color="accent" subtitle="Últimas 24h" />
        <KpiCard title="Sesiones Activas" value={data.activeSessions} icon={Users} color="blue" />
        <KpiCard title="AI Agents" value={data.aiAgentsDetected} icon={Bot} color="red" subtitle="Score ≥ 0.6" />
        <KpiCard title="Alertas" value={data.unresolvedAlerts} icon={Bell} color="green" subtitle="Sin resolver" />
      </div>

      <div className="mb-6">
        <RequestsChart data={data.requestsOverTime} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <ScoreDistribution data={data.scoreDistribution} />
        <TopSources data={data.topSources} />
      </div>

      <RecentAlerts data={data.recentAlerts} />
    </div>
  );
}

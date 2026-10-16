import type {
  DashboardOverview,
  HoneypotDto,
  SessionDto,
  SessionDetailDto,
  RequestLogDto,
  AlertSummary,
  DetectionRule,
  TokenExhaustOverview,
  ScenarioSummary,
  ScenarioDetail,
  ScenarioNode,
  ScenarioCredential,
  BlockedIp,
  SensorDto,
  SensorCreated,
  SensorBundleDto,
  SensorInstallInfo,
} from '../types';

const API_BASE = '/api';

export interface Me {
  username: string;
  role: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  // 401 fuera del propio flujo de auth = la sesión caducó -> avisa al AuthGate para re-loguear.
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new CustomEvent('moqesh:unauthorized'));
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  auth: {
    me: () => request<Me>('/auth/me'),
    login: (username: string, password: string) =>
      request<Me>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
    logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  },
  dashboard: {
    overview: () => request<DashboardOverview>('/dashboard/overview'),
    timeline: (from?: string) =>
      request<{ timestamp: string; count: number }[]>(
        `/dashboard/timeline${from ? `?from=${from}` : ''}`
      ),
    tokenExhaust: () => request<TokenExhaustOverview>('/dashboard/token-exhaust'),
  },
  honeypots: {
    list: () => request<HoneypotDto[]>('/honeypots'),
    get: (id: number) => request<HoneypotDto>(`/honeypots/${id}`),
    create: (data: { name: string; type: string; port: number }) =>
      request<HoneypotDto>('/honeypots', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<HoneypotDto>) =>
      request<void>(`/honeypots/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: number) =>
      request<void>(`/honeypots/${id}`, { method: 'DELETE' }),
    toggle: (id: number) =>
      request<{ isActive: boolean }>(`/honeypots/${id}/toggle`, { method: 'POST' }),
    upload: async (id: number, files: FileList) => {
      const form = new FormData();
      Array.from(files).forEach(f => form.append('files', f));
      const res = await fetch(`${API_BASE}/honeypots/${id}/upload`, { method: 'POST', body: form, credentials: 'include' });
      if (!res.ok) throw new Error(`Upload error: ${res.status}`);
      return res.json();
    },
  },
  sessions: {
    list: (params?: { minScore?: number; status?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.minScore) qs.set('minScore', String(params.minScore));
      if (params?.status) qs.set('status', params.status);
      if (params?.limit) qs.set('limit', String(params.limit));
      return request<SessionDto[]>(`/sessions?${qs}`);
    },
    get: (id: number) => request<SessionDetailDto>(`/sessions/${id}`),
    requests: (id: number) => request<RequestLogDto[]>(`/sessions/${id}/requests`),
  },
  requests: {
    list: (params?: { honeypotId?: number; limit?: number; offset?: number }) => {
      const qs = new URLSearchParams();
      if (params?.honeypotId) qs.set('honeypotId', String(params.honeypotId));
      if (params?.limit) qs.set('limit', String(params.limit));
      if (params?.offset) qs.set('offset', String(params.offset));
      return request<RequestLogDto[]>(`/requests?${qs}`);
    },
    get: (id: number) => request<RequestLogDto>(`/requests/${id}`),
  },
  alerts: {
    list: (params?: { severity?: string; acknowledged?: boolean; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.severity) qs.set('severity', params.severity);
      if (params?.acknowledged !== undefined) qs.set('acknowledged', String(params.acknowledged));
      if (params?.limit) qs.set('limit', String(params.limit));
      return request<AlertSummary[]>(`/alerts?${qs}`);
    },
    acknowledge: (id: number) =>
      request<void>(`/alerts/${id}/acknowledge`, { method: 'PUT' }),
  },
  rules: {
    list: () => request<DetectionRule[]>('/rules'),
    update: (id: number, data: { weight?: number; isActive?: boolean }) =>
      request<void>(`/rules/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  },
  scenarios: {
    list: () => request<ScenarioSummary[]>('/scenarios'),
    get: (id: number) => request<ScenarioDetail>(`/scenarios/${id}`),
    activate: (id: number) => request<void>(`/scenarios/${id}/activate`, { method: 'POST' }),
    deactivate: (id: number) => request<void>(`/scenarios/${id}/deactivate`, { method: 'POST' }),
    delete: (id: number) => request<void>(`/scenarios/${id}`, { method: 'DELETE' }),
    import: (pack: unknown, activate: boolean) =>
      request<{ id: number }>(`/scenarios/import?activate=${activate}`, { method: 'POST', body: JSON.stringify(pack) }),
    builtins: () => request<string[]>('/scenarios/builtins'),
    importBuiltin: (name: string, activate: boolean) =>
      request<{ id: number }>(`/scenarios/builtins/${name}?activate=${activate}`, { method: 'POST' }),
    exportUrl: (id: number) => `${API_BASE}/scenarios/${id}/export`,
    addNode: (id: number, node: Partial<ScenarioNode>) =>
      request<ScenarioNode>(`/scenarios/${id}/nodes`, { method: 'POST', body: JSON.stringify(node) }),
    updateNode: (nodeId: number, node: Partial<ScenarioNode>) =>
      request<ScenarioNode>(`/scenarios/nodes/${nodeId}`, { method: 'PUT', body: JSON.stringify(node) }),
    deleteNode: (nodeId: number) => request<void>(`/scenarios/nodes/${nodeId}`, { method: 'DELETE' }),
    addCred: (id: number, cred: Partial<ScenarioCredential>) =>
      request<ScenarioCredential>(`/scenarios/${id}/credentials`, { method: 'POST', body: JSON.stringify(cred) }),
    updateCred: (credId: number, cred: Partial<ScenarioCredential>) =>
      request<ScenarioCredential>(`/scenarios/credentials/${credId}`, { method: 'PUT', body: JSON.stringify(cred) }),
    deleteCred: (credId: number) => request<void>(`/scenarios/credentials/${credId}`, { method: 'DELETE' }),
  },
  blocks: {
    list: () => request<BlockedIp[]>('/blocks'),
    block: (ip: string, reason?: string) => request<void>('/blocks', { method: 'POST', body: JSON.stringify({ ip, reason }) }),
    unblock: (id: number) => request<void>(`/blocks/${id}`, { method: 'DELETE' }),
  },
  sensors: {
    list: () => request<SensorDto[]>('/sensors'),
    get: (id: number) => request<SensorDto>(`/sensors/${id}`),
    create: (data: {
      name: string;
      kind: 'agent' | 'agentless';
      coveredUrl?: string;
      coveredApp?: string;
      basePath?: string;
      generationMode?: string;
      realismLevel?: number;
      scenarioId?: number | null;
    }) => request<SensorCreated>('/sensors', { method: 'POST', body: JSON.stringify(data) }),
    enable: (id: number) =>
      request<{ id: number; enabled: boolean }>(`/sensors/${id}/enable`, { method: 'POST' }),
    disable: (id: number) =>
      request<{ id: number; enabled: boolean }>(`/sensors/${id}/disable`, { method: 'POST' }),
    rotateSeed: (id: number) =>
      request<{ id: number; seed: string }>(`/sensors/${id}/rotate-seed`, { method: 'POST' }),
    rotateKey: (id: number) =>
      request<SensorCreated>(`/sensors/${id}/rotate-key`, { method: 'POST' }),
    // Dar de baja: el backend responde 204 sin cuerpo, por lo que no se parsea JSON.
    remove: async (id: number): Promise<void> => {
      const res = await fetch(`${API_BASE}/sensors/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
    },
    install: (id: number) => request<SensorInstallInfo>(`/sensors/${id}/install`),
    bundles: (id: number) => request<SensorBundleDto[]>(`/sensors/${id}/bundles`),
    generateBundles: (id: number, count = 3) =>
      request<SensorBundleDto[]>(`/sensors/${id}/bundles?count=${count}`, { method: 'POST' }),
  },
};

// Enlaces de descarga directos (fuera de /api).
export const downloads = {
  // El filename del bundle llega con extensión; la ruta la espera SIN extensión.
  bundle: (filename: string) =>
    `/download/bundle/${filename.replace(/\.(tar\.gz|tgz|zip)$/i, '')}`,
  shipper: (sensorId: number) => `/download/shipper/${sensorId}`,
};

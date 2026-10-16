export interface DashboardOverview {
  totalRequests: number;
  activeSessions: number;
  aiAgentsDetected: number;
  unresolvedAlerts: number;
  requestsOverTime: TimeSeriesPoint[];
  scoreDistribution: ScoreDistributionPoint[];
  topSources: TopSourceEntry[];
  recentAlerts: AlertSummary[];
}

export interface TimeSeriesPoint {
  timestamp: string;
  count: number;
}

export interface ScoreDistributionPoint {
  range: string;
  count: number;
}

export interface TopSourceEntry {
  ip: string;
  requestCount: number;
  maxScore: number;
}

export interface AlertSummary {
  id: number;
  severity: string;
  title: string;
  createdAt: string;
  acknowledged: boolean;
}

export interface SessionDto {
  id: number;
  sourceIp: string;
  userAgent: string | null;
  firstSeen: string;
  lastSeen: string;
  requestCount: number;
  aiProbabilityScore: number;
  status: string;
  tokensEstimated: number;
  nodesServed: number;
  timeWastedMs: number;
  maxDepthReached: number;
  matchedRules: string | null;
  verdict: string;
  verdictConfidence: number;
  verdictReasoning: string | null;
  modelAttribution: string | null;
}

export interface SessionDetailDto {
  session: SessionDto;
  requests: RequestLogDto[];
  alerts: AlertSummary[];
  progress: ScenarioProgressDto | null;
}

export interface TokenExhaustOverview {
  totalTokensBurned: number;
  totalTimeWastedMs: number;
  totalNodesServed: number;
  sessionsEngaged: number;
  topBurners: TokenBySourceEntry[];
  byModel: ModelAttributionEntry[];
}

export interface TokenBySourceEntry {
  ip: string;
  tokens: number;
  timeWastedMs: number;
  nodes: number;
  maxDepth: number;
  score: number;
  verdict: string;
}

export interface ModelAttributionEntry {
  model: string;
  sessions: number;
  tokens: number;
  avgScore: number;
}

export interface ScenarioSummary {
  id: number;
  name: string;
  description: string;
  isActive: boolean;
  createdAt: string;
  nodeCount: number;
  credCount: number;
}

export interface ScenarioNode {
  id: number;
  scenarioId: number;
  path: string;
  visibility: string;
  kind: string;
  contentType: string;
  bodyTemplate: string;
  requiresCredentialKey: string | null;
  grantsCredentialKeys: string | null;
  hintedByPaths: string | null;
  stage: number;
  binaryKind: string;
  binarySecret: string;
}

export interface ScenarioCredential {
  id: number;
  scenarioId: number;
  key: string;
  username: string | null;
  secret: string;
  kind: string;
  foundInPath: string | null;
  usableAtPath: string | null;
}

export interface ScenarioDetail {
  scenario: { id: number; name: string; description: string; isActive: boolean; createdAt: string };
  nodes: ScenarioNode[];
  credentials: ScenarioCredential[];
}

export interface ScenarioProgressDto {
  stageReached: number;
  credentialsObtained: string;
  credentialsUsed: string;
  hiddenHits: number;
  decompileFollow: boolean;
  failedAuthAttempts: number;
}

export interface BlockedIp {
  id: number;
  ip: string;
  reason: string;
  source: string;
  sessionId: number | null;
  active: boolean;
  createdAt: string;
}

export interface RequestLogDto {
  id: number;
  honeypotId: number;
  sessionId: number | null;
  timestamp: string;
  sourceIp: string;
  method: string;
  path: string;
  userAgent: string | null;
  responseCode: number;
  processingTimeMs: number;
}

export interface HoneypotDto {
  id: number;
  name: string;
  type: string;
  port: number;
  isActive: boolean;
  tokenExhaustEnabled: boolean;
  createdAt: string;
  requestCount: number;
}

export interface DetectionRule {
  id: number;
  name: string;
  description: string;
  weight: number;
  ruleType: string;
  isActive: boolean;
  mitreAttackId: string | null;
  mitreAtlasId: string | null;
}

export type SensorKind = 'local' | 'agent' | 'agentless';
export type SensorStatus = 'online' | 'offline' | 'unknown';

export interface SensorDto {
  id: number;
  name: string;
  kind: SensorKind;
  enabled: boolean;
  status: SensorStatus;
  lastSeen: string | null;
  lastIngestAt: string | null;
  seed: string;
  scenarioId: number | null;
  generationMode: string;
  realismLevel: number;
  coveredUrl: string;
  coveredApp: string;
  basePath: string;
  agentVersion: string | null;
  configVersion: number;
  createdAt: string;
  sessionCount: number;
  alertCount: number;
}

export interface SensorCreated {
  id: number;
  name: string;
  kind: SensorKind;
  keyId: string;
  apiSecret: string;
  installToken: string;
  installCommand: string;
}

export interface SensorBundleDto {
  id: number;
  sensorId: number;
  filename: string;
  seed: string;
  archiveFormat: string;
  createdAt: string;
}

export interface SensorInstallInfo {
  kind: SensorKind;
  oneCommand: string;
  inspectCommand: string;
  agentless?: {
    steps: string[];
    cron: string;
    shipperUrl?: string;
    note: string;
  } | null;
}

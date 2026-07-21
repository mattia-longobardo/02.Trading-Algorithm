// Tipi del contratto API backend (FastAPI) — tutte le rotte passano da /api/*

export type Environment = "demo" | "real";

export interface CircuitBreakerStatus {
  tripped: boolean;
  reason: string | null;
  until: string | null;
}

export interface Status {
  environment: Environment;
  kill_switch_active: boolean;
  circuit_breaker: CircuitBreakerStatus;
  run_in_progress: boolean;
  next_run_at: string | null;
  equity_usd: number | null;
  equity_change_day_pct: number | null;
}

export interface RunSummary {
  candidates: number;
  proposed: number;
  approved: number;
  rejected: number;
  executed: number;
  /** Presenti dal journal, ma non su run vecchie: sempre opzionali. */
  skipped?: number;
  failed?: number;
  anomalies?: number;
  errors?: string[];
}

export interface Run {
  run_id: string;
  started_at: string;
  environment: Environment;
  summary: RunSummary | null;
}

export interface RunsResponse {
  runs: Run[];
}

export type DecisionStage =
  | "analyst"
  | "debate"
  | "portfolio"
  | "risk"
  | "reconcile_anomaly";

export interface Decision {
  id: string;
  symbol: string;
  stage: DecisionStage;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DecisionsResponse {
  run_id: string;
  /** Anagrafica della run; assente sulle risposte servite da backend vecchi. */
  run?: Run;
  decisions: Decision[];
}

export type ExecutionStatus = "filled" | "failed" | "skipped" | "rejected";

export interface Execution {
  id: string;
  run_id: string;
  symbol: string;
  side: "buy" | "sell";
  amount_usd: number;
  status: ExecutionStatus;
  detail: string | null;
  execution_price: number | null;
  etoro_position_id: string | number | null;
  created_at: string;
}

export interface ExecutionsResponse {
  executions: Execution[];
}

export interface Position {
  etoro_position_id: string | number;
  symbol: string;
  instrument_id: number;
  amount_usd: number;
  entry_price: number;
  current_price: number | null;
  unrealized_pnl_usd: number | null;
  unrealized_pnl_pct: number | null;
  sector: string | null;
  opened_at: string;
}

export interface Anomaly {
  symbol: string;
  detail: string;
  detected_at: string;
}

export interface Portfolio {
  positions: Position[];
  cash_usd: number;
  equity_usd: number;
  exposure_usd: number;
  anomalies: Anomaly[];
  max_trade_amount_usd: number;
  capital_source: "etoro";
}

export interface BacktestMetrics {
  total_return_pct: number | null;
  cagr_pct: number | null;
  volatility_pct: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown_pct: number | null;
  calmar: number | null;
  alpha: number | null;
  beta: number | null;
  information_ratio: number | null;
  win_rate_pct: number | null;
  profit_factor: number | null;
  recovery_factor: number | null;
  expectancy_usd: number | null;
  exposure_pct: number | null;
  max_win_usd: number | null;
  max_loss_usd: number | null;
  std_win_usd: number | null;
  std_loss_usd: number | null;
}

export interface DateRangeValue {
  from: string;
  to: string;
}

export interface RiskLimits {
  max_position_pct_equity: number;
  max_total_exposure_pct: number;
  max_sector_exposure_pct: number;
  max_open_positions: number;
  max_orders_per_run: number;
  max_orders_per_day: number;
  min_cash_buffer_pct: number;
}

export interface BacktestSummary {
  metrics: BacktestMetrics;
  n_closed_trades: number;
  n_days: number;
  insufficient_sample: boolean;
  annualization_available: boolean;
}

export interface EquityPoint {
  date: string;
  equity_usd: number;
  spy_lump_sum_usd: number | null;
  spy_cash_flow_matched_usd: number | null;
}

export interface EquityCurve {
  points: EquityPoint[];
  note_dividends: string;
}

export interface ClosedTrade {
  etoro_position_id: string | number;
  symbol: string;
  amount_usd: number;
  entry_price: number;
  close_price: number | null;
  realized_pnl_usd: number | null;
  opened_at: string;
  closed_at: string;
  close_reason: string | null;
}

export interface TradesResponse {
  trades: ClosedTrade[];
}

export interface MonthlyRow {
  year: number;
  months: (number | null)[];
}

export interface MonthlyReturns {
  rows: MonthlyRow[];
}

export type RiskBand = "low" | "medium" | "high" | "extreme";

export interface RiskComponent {
  key: string;
  label: string;
  weight_pct: number;
  value_0_10: number;
  explanation: string;
  suggestion: string | null;
}

export interface RiskScore {
  score: number;
  band: RiskBand;
  components: RiskComponent[];
}

export interface RiskHistoryPoint {
  date: string;
  score: number;
}

export interface RiskHistory {
  points: RiskHistoryPoint[];
}

export interface IngestResult {
  filename: string;
  chunks_indexed: number;
  /** Titoli impattati, dedotti dal contenuto del documento. */
  tickers: string[];
}

export interface KnowledgeStatus {
  qdrant_up: boolean;
  collections: {
    news_kb: number;
    trade_memory: number;
  };
  rss_feeds: string[];
  last_fetch: string | null;
}

export interface AppSettings {
  environment: Environment;
  /** Orario della run automatica, SEMPRE in UTC. */
  schedule_utc: string;
  /** Fuso di sola presentazione: non sposta l'orario di esecuzione. */
  timezone: string;
  /** Valuta di sola presentazione: il journal resta in USD. */
  currency: string;
  weekdays_only: boolean;
  live_ack: string | null;
  api_keys_configured: boolean;
  openai_configured: boolean;
  risk_limits: RiskLimits;
}

export interface SettingsUpdate {
  environment?: Environment;
  schedule_utc?: string;
  timezone?: string;
  currency?: string;
  weekdays_only?: boolean;
  risk_limits?: RiskLimits;
  confirmation?: boolean;
}

export interface CurrencyOption {
  code: string;
  label: string;
}

/** Tassi USD→valuta serviti da /fx/rates (fonte BCE via Frankfurter). */
export interface FxRates {
  base: string;
  rates: Record<string, number>;
  fetched_at: string | null;
  /** true = tasso non aggiornato (rete giù): la UI lo segnala invece di mentire. */
  stale: boolean;
  source: string;
  currencies: CurrencyOption[];
}

export interface AuditEntry {
  id: string | number;
  changed_at: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  source: string;
}

export interface AuditResponse {
  entries: AuditEntry[];
}

export interface RunStartResponse {
  run_id: string;
}

export interface AccountCredentials {
  user_id: string;
  email: string | null;
  display_name: string | null;
  etoro_api_key_configured: boolean;
  etoro_user_key_configured: boolean;
  openai_api_key_configured: boolean;
}

export interface TradeItem {
  id: string;
  position_id: string | number | null;
  execution_id: string | null;
  symbol: string;
  side: "buy" | "sell";
  status: string;
  amount_usd: number;
  entry_price: number | null;
  current_price: number | null;
  pnl_usd: number | null;
  created_at: string;
  detail: string | null;
  can_close: boolean;
  can_cancel: boolean;
}

export interface TradeHistoryItem {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  status: string;
  amount_usd: number;
  price: number | null;
  pnl_usd: number | null;
  opened_at: string;
  closed_at: string | null;
  detail: string | null;
}

export interface NewsItem {
  text: string;
  source: string;
  tickers: string[];
  published_at: string;
  url?: string;
}

export interface ReportItem {
  id: string;
  cadence: "weekly" | "monthly" | "quarterly" | "semiannual" | "annual";
  name: string;
  filename: string;
  size_bytes: number;
  updated_at: string;
  period_end: string;
}

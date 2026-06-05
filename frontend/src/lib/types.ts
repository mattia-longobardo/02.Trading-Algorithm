export type UserRole = "admin" | "user";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: UserRole;
}

export interface UserRow extends AuthUser {
  disabled: number;
  created_at: string;
  updated_at: string;
}

export type TradeStatus = "PENDING" | "OPEN" | "CLOSED" | "CANCELLED";
export type TradeCategory = "STOCK" | "CRYPTO";

export interface Trade {
  id: number;
  symbol: string;
  category: TradeCategory;
  direction: string;
  status: TradeStatus;
  entry_price: number;
  target_entry_price: number | null;
  quantity: number;
  allocated_capital: number;
  take_profit: number | null;
  trailing_take_profit_distance: number | null;
  trailing_take_profit_activation_pct: number | null;
  stop_loss: number | null;
  trailing_stop_distance: number | null;
  high_water_mark: number | null;
  trailing_take_profit_price: number | null;
  trailing_stop_price: number | null;
  open_timestamp: string | null;
  close_timestamp: string | null;
  close_price: number | null;
  current_price: number | null;
  pnl: number | null;
  realized_pnl: number;
  unrealized_pnl: number;
  close_reason: string | null;
  instrument_id: number | null;
  position_id: string | null;
  order_reference_id: string | null;
  reasoning: string | null;
  confidence: number | null;
  account_currency: string;
  created_at: string;
  updated_at: string;
  trade_score: number | null;
}

export interface Metrics {
  total_pnl_abs: number;
  total_pnl_pct: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe: number;
  n_trades: number;
  n_open: number;
  n_pending: number;
  account_equity: number;
  currency: string;
  account_currency: string;
}

export interface EquityPoint {
  t: string;
  equity: number;
}

export interface PnlBySymbolRow {
  symbol: string;
  pnl_abs: number;
  pnl_pct: number;
  n_trades: number;
}

export interface AllocationCategory {
  category: string;
  value: number;
}

export interface AllocationSymbol {
  symbol: string;
  category: string;
  value: number;
}

export interface ReturnsBin {
  lo: number;
  hi: number;
  count: number;
}

export interface ReportRow {
  id: number;
  filename: string;
  type: "weekly" | "quarterly" | "biannual" | "annual" | "other";
  format: "json" | "pdf";
  size_bytes: number;
  generated_at: string;
  folder_id: number | null;
  tags: string | null;
}

export interface ReportFolder {
  id: number;
  name: string;
  parent_id: number | null;
  created_at: string;
  created_by: number | null;
}

export type PromptKey =
  | "new_signal"
  | "batch_signals"
  | "pending_review"
  | "protection_review"
  | "universe_dossier"
  | "universe_shortlist"
  | "universe_final"
  | "universe_final_from_dossiers";

export const PROMPT_KEYS: PromptKey[] = [
  "new_signal",
  "batch_signals",
  "pending_review",
  "protection_review",
  "universe_dossier",
  "universe_shortlist",
  "universe_final",
  "universe_final_from_dossiers",
];

export interface PromptSummary {
  key: PromptKey;
  current_version_id: number;
  updated_at: string;
}

export interface PromptDetail {
  key: PromptKey;
  content: string;
  version_id: number;
  updated_at: string;
}

export interface PromptVersion {
  id: number;
  prompt_key: PromptKey;
  content: string;
  comment: string | null;
  saved_by: number | null;
  saved_by_username: string | null;
  saved_at: string;
  is_current: number;
}

export interface SettingsResponse {
  values: Record<string, unknown>;
  restart_required: boolean;
  active_providers?: string[];
}

export interface AuditEntry {
  id: number;
  actor_id: number | null;
  actor_name: string;
  entity: string;
  entity_id: string | null;
  action: string;
  before_json: string | null;
  after_json: string | null;
  created_at: string;
}

export interface LivePosition {
  id: number;
  symbol: string;
  category: TradeCategory;
  units: number;
  entry_price: number;
  current_price: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  take_profit: number | null;
  stop_loss: number | null;
  position_id: string | null;
  instrument_id: number | null;
  is_buy: boolean;
}

export interface LiveSnapshot {
  ts: string;
  currency: string;
  equity: number | null;
  cash: number | null;
  positions: LivePosition[];
}

export type LiveStatus = "connecting" | "live" | "stale" | "reconnecting";

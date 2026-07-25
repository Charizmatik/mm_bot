export type Pair = {
  id: string; exchange: string; symbol: string; base_asset: string; quote_asset: string;
  lot_quote: string; spread_pct: string;
  base_balance_trigger: string; base_balance_limit: string;
  quote_balance_trigger: string; quote_balance_limit: string;
  order_offset_pct: string; red_line_pct: string; pause_minutes: number;
  price_precision: number; quantity_precision: number; irb: number;
  status: string; enabled: boolean; paused_until: string | null; last_error: string | null;
};

export type Runtime = {
  pair: Pair; bid: string | null; ask: string | null; quote_updated_at: string | null;
  bid_order: ActiveOrder | null; ask_order: ActiveOrder | null;
  red_line: RedLine | null;
  base_free: string | null; quote_free: string | null; balance_updated_at: string | null; open_orders: number;
};

export type ActiveOrder = {
  price: string; distance_pct: string | null;
};

export type RedLine = {
  filled_side: 'BUY' | 'SELL'; reference_price: string; trigger_price: string; distance_pct: string | null;
};

export type BotEvent = {
  id: string; pair_id: string | null; level: string; kind: string; message: string; created_at: string;
};

export type Page<T> = {
  items: T[]; total: number; page: number; page_size: number; pages: number;
};

export type PairForm = {
  symbol: string; base_asset: string; quote_asset: string; lot_quote: string; spread_pct: string;
  base_balance_trigger: string; base_balance_limit: string;
  quote_balance_trigger: string; quote_balance_limit: string;
  order_offset_pct: string; red_line_pct: string;
  pause_minutes: number; price_precision: number; quantity_precision: number;
};

export type ProfitBucket = {
  quote_asset: string; trading_volume: string; trading_volume_usdt: string;
  gross_profit: string; commission: string; net_profit: string;
};

export type PairStatistics = ProfitBucket & {
  pair_id: string; symbol: string; successful_trades: number; unsuccessful_trades: number;
  total_trades: number; success_rate_pct: string;
};

export type Statistics = {
  successful_trades: number; unsuccessful_trades: number; total_trades: number;
  success_rate_pct: string; by_quote_asset: ProfitBucket[]; pairs: PairStatistics[];
};

export type AnalyticsPeriod = {
  period_start: string; period_end: string;
  successful_trades: number; unsuccessful_trades: number; total_trades: number;
  success_rate_pct: string; trading_volume_usdt: string; by_quote_asset: ProfitBucket[];
};

export type AnalyticsReport = {
  date_from: string | null; date_to: string; granularity: 'day' | 'week' | 'month';
  totals: Statistics; periods: AnalyticsPeriod[];
};

export type ExchangeSymbol = {
  symbol: string; base_asset: string; quote_asset: string;
  price_precision: number; quantity_precision: number;
};

export type OrderFill = {
  id: string; exchange_trade_id: string; price: string; quantity: string;
  quote_quantity: string; quote_quantity_usdt: string | null;
  commission: string; commission_asset: string; commission_quote: string; executed_at: string;
};

export type OrderDetails = {
  id: string; cycle_id: string; pair_id: string; symbol: string; base_asset: string; quote_asset: string;
  cycle_status: string; exchange_order_id: string; client_order_id: string;
  side: 'BUY' | 'SELL'; status: string; price: string; quantity: string;
  executed_quantity: string; quote_value: string; execution_pct: string;
  created_at: string; updated_at: string; fills: OrderFill[];
};

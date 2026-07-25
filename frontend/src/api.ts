import type {
  AnalyticsReport, BotEvent, ExchangeSymbol, OrderDetails, Page, Pair, PairForm, Runtime, Statistics,
} from './types';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => call<{status: string; dry_run: boolean}>('/health'),
  pairs: () => call<Runtime[]>('/pairs'),
  events: (page = 1) => call<Page<BotEvent>>(`/events?page=${page}&page_size=10`),
  orders: (page = 1, pairId = 'all') => call<Page<OrderDetails>>(
    `/orders?page=${page}&page_size=10${pairId === 'all' ? '' : `&pair_id=${encodeURIComponent(pairId)}`}`,
  ),
  statistics: (paperProfit = false) => call<Statistics>(`/statistics?paper_profit=${paperProfit}`),
  analytics: (params: {
    dateFrom?: string; dateTo?: string; granularity: string; pairId?: string; paperProfit?: boolean;
  }) => {
    const query = new URLSearchParams({granularity: params.granularity});
    if (params.dateFrom) query.set('date_from', params.dateFrom);
    if (params.dateTo) query.set('date_to', params.dateTo);
    if (params.pairId && params.pairId !== 'all') query.set('pair_id', params.pairId);
    if (params.paperProfit) query.set('paper_profit', 'true');
    return call<AnalyticsReport>(`/analytics?${query}`);
  },
  symbols: (query: string) => call<ExchangeSymbol[]>(`/symbols?q=${encodeURIComponent(query)}&limit=30`),
  create: (form: PairForm) => call<Pair>('/pairs', { method: 'POST', body: JSON.stringify(form) }),
  update: (id: string, form: PairForm) => call<Pair>(`/pairs/${id}`, {
    method: 'PUT', body: JSON.stringify(form),
  }),
  start: (id: string) => call<Pair>(`/pairs/${id}/start`, { method: 'POST' }),
  stop: (id: string) => call<Pair>(`/pairs/${id}/stop`, { method: 'POST' }),
  irb: (id: string, value: number, note: string) =>
    call<Pair>(`/pairs/${id}/irb`, { method: 'POST', body: JSON.stringify({ value, note }) }),
};

import type { BotEvent, ExchangeSymbol, OrderDetails, Pair, PairForm, Runtime, Statistics } from './types';

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
  events: () => call<BotEvent[]>('/events?limit=80'),
  orders: () => call<OrderDetails[]>('/orders?limit=200'),
  statistics: (paperProfit = false) => call<Statistics>(`/statistics?paper_profit=${paperProfit}`),
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

import { FormEvent, KeyboardEvent, useCallback, useEffect, useState } from 'react';
import { api } from './api';
import type { BotEvent, ExchangeSymbol, OrderDetails, PairForm, Runtime, Statistics } from './types';

const initial: PairForm = {
  symbol: 'BTCUSDT', base_asset: 'BTC', quote_asset: 'USDT', lot_quote: '100', spread_pct: '0.15',
  base_balance_trigger: '0.01', base_balance_limit: '0.005',
  quote_balance_trigger: '500', quote_balance_limit: '200',
  order_offset_pct: '0.005', red_line_pct: '0.5',
  pause_minutes: 2, price_precision: 2, quantity_precision: 6,
};

const labels: Record<string, string> = {
  stopped: 'Зупинено', running: 'Працює', paused: 'Пауза', limit_reached: 'Ліміт', error: 'Помилка',
};

const orderLabels: Record<string, string> = {
  NEW: 'Виставлений', PARTIALLY_FILLED: 'Частково виконаний', FILLED: 'Виконаний',
  CANCELED: 'Скасований', REJECTED: 'Відхилений', EXPIRED: 'Прострочений',
};

function formatNumber(value: string | number | null, precision: number, fixed = false): string {
  if (value === null) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const digits = Math.max(0, Math.min(precision, 12));
  return number.toLocaleString('en-US', {
    minimumFractionDigits: fixed ? digits : 0,
    maximumFractionDigits: digits,
  });
}

function compactDecimal(value: string): string {
  return value
    .replace(/(\.\d*?[1-9])0+$/, '$1')
    .replace(/\.0+$/, '');
}

function App() {
  const [pairs, setPairs] = useState<Runtime[]>([]);
  const [events, setEvents] = useState<BotEvent[]>([]);
  const [orders, setOrders] = useState<OrderDetails[]>([]);
  const [orderPair, setOrderPair] = useState('all');
  const [stats, setStats] = useState<Statistics>({successful_trades: 0, unsuccessful_trades: 0,
    total_trades: 0, success_rate_pct: '0', by_quote_asset: [], pairs: []});
  const [paperProfit, setPaperProfit] = useState(() => localStorage.getItem('paper-profit') === 'true');
  const [form, setForm] = useState<PairForm>(initial);
  const [dryRun, setDryRun] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [health, pairData, eventData, statsData, orderData] = await Promise.all([
        api.health(), api.pairs(), api.events(), api.statistics(paperProfit), api.orders(),
      ]);
      setDryRun(health.dry_run); setPairs(pairData); setEvents(eventData); setStats(statsData);
      setOrders(orderData); setError('');
    } catch (e) { setError((e as Error).message); }
  }, [paperProfit]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function act(id: string, action: 'start' | 'stop') {
    setBusy(id + action);
    try { await api[action](id); await refresh(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  }

  function openCreate() {
    setEditingId(null); setForm(initial); setShowForm(true);
  }

  function openEdit(runtime: Runtime) {
    const p = runtime.pair;
    setEditingId(p.id);
    setForm({
      symbol: p.symbol, base_asset: p.base_asset, quote_asset: p.quote_asset,
      lot_quote: compactDecimal(p.lot_quote), spread_pct: compactDecimal(p.spread_pct),
      base_balance_trigger: compactDecimal(p.base_balance_trigger),
      base_balance_limit: compactDecimal(p.base_balance_limit),
      quote_balance_trigger: compactDecimal(p.quote_balance_trigger),
      quote_balance_limit: compactDecimal(p.quote_balance_limit),
      order_offset_pct: compactDecimal(p.order_offset_pct),
      red_line_pct: compactDecimal(p.red_line_pct),
      pause_minutes: p.pause_minutes, price_precision: p.price_precision,
      quantity_precision: p.quantity_precision,
    });
    setShowForm(true);
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(editingId ? `${editingId}edit` : 'create');
    try {
      if (editingId) await api.update(editingId, form); else await api.create(form);
      setShowForm(false); setEditingId(null); setForm(initial); await refresh();
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  }

  const totalVolumeUsdt = stats.by_quote_asset.reduce(
    (sum, bucket) => sum + Number(bucket.trading_volume_usdt), 0,
  );
  const filteredOrders = orderPair === 'all' ? orders : orders.filter(order => order.pair_id === orderPair);

  return <main>
    <header>
      <div><span className="eyebrow">MEXC · SPOT</span><h1>Inventory Market Maker</h1></div>
      <div className={`mode ${dryRun ? 'paper' : 'live'}`}><i />{dryRun ? 'DRY RUN' : 'LIVE TRADING'}</div>
    </header>

    {error && <div className="error"><span>{error}</span><button onClick={() => setError('')}>×</button></div>}

    <section className="intro">
      <div><p className="kicker">Панель стратегії</p><h2>Ліквідність під контролем.</h2>
      <p>Два ордери навколо стакана, inventory skew за ІРБ і жорстка зупинка на ліміті.</p></div>
      <button className="primary" onClick={() => {
        if (showForm) { setShowForm(false); setEditingId(null); setForm(initial); } else openCreate();
      }}>{showForm ? 'Закрити' : '+ Додати пару'}</button>
    </section>

    <section className="stats-section">
      <div className="section-title"><h3>Статистика торгівлі</h3><div className="stats-controls"><span>закриті цикли</span>
        <label className="pp-toggle" title="Не враховувати RED_LINE як зафіксований збиток">
          <input type="checkbox" checked={paperProfit} onChange={event => {
            const checked = event.target.checked;
            localStorage.setItem('paper-profit', String(checked));
            setPaperProfit(checked);
          }} /><i /><b>ПП</b>
        </label></div></div>
      <div className="stats-grid">
        <Stat label="Усього" value={stats.total_trades.toString()} />
        <Stat label="Вдалі" value={stats.successful_trades.toString()} tone="good" />
        <Stat label="Невдалі" value={stats.unsuccessful_trades.toString()} tone="bad" />
        <Stat label="Success rate" value={`${Number(stats.success_rate_pct).toFixed(1)}%`} />
        <Stat label="Обсяг у USDT" value={formatNumber(totalVolumeUsdt, 2)} />
      </div>
      {stats.by_quote_asset.length > 0 && <div className="profit-grid">{stats.by_quote_asset.map(bucket =>
        <article key={bucket.quote_asset}>
          <div><span>Результат у {bucket.quote_asset}</span><strong className={Number(bucket.net_profit) >= 0 ? 'positive' : 'negative'}>
            {Number(bucket.net_profit).toFixed(6)} {bucket.quote_asset}</strong></div>
          <dl><div><dt>Gross profit</dt><dd>{Number(bucket.gross_profit).toFixed(6)}</dd></div>
            <div><dt>Комісії</dt><dd>{Number(bucket.commission).toFixed(6)}</dd></div></dl>
        </article>)}</div>}
      {stats.pairs.length > 0 && <div className="pair-stats">
        <div className="section-title"><h3>Прибуток та обсяг по парах</h3><span>{stats.pairs.length} пар</span></div>
        <div className="table-scroll"><table><thead><tr><th>Пара</th><th>Угоди</th><th>Обсяг</th>
          <th>Обсяг, USDT</th><th>Комісія</th><th>Чистий прибуток</th></tr></thead><tbody>
          {stats.pairs.map(pair => <tr key={pair.pair_id}><td><strong>{pair.symbol}</strong></td>
            <td>{pair.total_trades} ({Number(pair.success_rate_pct).toFixed(1)}%)</td>
            <td>{formatNumber(pair.trading_volume, 6)} {pair.quote_asset}</td>
            <td>{formatNumber(pair.trading_volume_usdt, 2)} USDT</td>
            <td>{formatNumber(pair.commission, 6)} {pair.quote_asset}</td>
            <td className={Number(pair.net_profit) >= 0 ? 'positive' : 'negative'}>
              {formatNumber(pair.net_profit, 6)} {pair.quote_asset}</td></tr>)}</tbody></table></div>
      </div>}
    </section>

    {showForm && <form className="create-form" onSubmit={submit}>
      <h3>{editingId ? 'Редагування торгової пари' : 'Нова торгова пара'}</h3>
      {editingId && <p className="form-note">ІРБ обчислюється ботом автоматично й не є параметром конфігурації.</p>}
      <div className="form-grid">
        <SymbolPicker value={form.symbol} onSelect={item => setForm({...form, symbol: item.symbol,
          base_asset: item.base_asset, quote_asset: item.quote_asset,
          price_precision: item.price_precision, quantity_precision: item.quantity_precision})} />
        <Field label="Базовий актив" value={form.base_asset} readOnly />
        <Field label="Актив котирування" value={form.quote_asset} readOnly />
        <Field label={`Лот, ${form.quote_asset || 'quote'}`} type="number" value={form.lot_quote} onChange={v => setForm({...form, lot_quote: v})} />
        <Field label="Спред, %" type="number" value={form.spread_pct} onChange={v => setForm({...form, spread_pct: v})} />
        <Field label="Зміщення, %" type="number" value={form.order_offset_pct} onChange={v => setForm({...form, order_offset_pct: v})} />
        <Field label="Червона лінія, %" type="number" value={form.red_line_pct} onChange={v => setForm({...form, red_line_pct: v})} />
        <Field label="Пауза, хв" type="number" value={form.pause_minutes} onChange={v => setForm({...form, pause_minutes: +v})} />
        <Field label={`Тригер ${form.base_asset || 'base'}`} type="number" value={form.base_balance_trigger} onChange={v => setForm({...form, base_balance_trigger: v})} />
        <Field label={`Ліміт ${form.base_asset || 'base'}`} type="number" value={form.base_balance_limit} onChange={v => setForm({...form, base_balance_limit: v})} />
        <Field label={`Тригер ${form.quote_asset || 'quote'}`} type="number" value={form.quote_balance_trigger} onChange={v => setForm({...form, quote_balance_trigger: v})} />
        <Field label={`Ліміт ${form.quote_asset || 'quote'}`} type="number" value={form.quote_balance_limit} onChange={v => setForm({...form, quote_balance_limit: v})} />
        <Field label="Знаків ціни" type="number" value={form.price_precision} onChange={v => setForm({...form, price_precision: +v})} />
        <Field label="Знаків кількості" type="number" value={form.quantity_precision} onChange={v => setForm({...form, quantity_precision: +v})} />
      </div>
      <button className="primary" disabled={busy === 'create' || busy.endsWith('edit')}>
        {busy === 'create' || busy.endsWith('edit') ? 'Зберігаю…' : editingId ? 'Зберегти всі зміни' : 'Створити пару'}</button>
    </form>}

    <section className="pairs">
      <div className="section-title"><h3>Торгові пари</h3><span>{pairs.length} конфігурацій</span></div>
      {pairs.length === 0 ? <div className="empty">Ще немає торгових пар. Додайте першу конфігурацію.</div> :
        <div className="pair-grid">{pairs.map(runtime => <PairCard key={runtime.pair.id} runtime={runtime}
          busy={busy} onAct={act} onEdit={openEdit} />)}</div>}
    </section>

    <section className="orders-section">
      <div className="section-title"><h3>Ордери та виконання</h3><span>{filteredOrders.length} із {orders.length}</span></div>
      <div className="order-toolbar"><label><span>Торгова пара</span><select value={orderPair}
        onChange={event => setOrderPair(event.target.value)}><option value="all">Усі пари</option>
        {pairs.map(runtime => <option value={runtime.pair.id} key={runtime.pair.id}>{runtime.pair.symbol}</option>)}</select></label></div>
      <div className="order-list">{filteredOrders.length === 0 ? <div className="empty">Ордерів ще немає.</div> :
        filteredOrders.map(order => <OrderRow order={order} key={order.id} />)}</div>
    </section>

    <section className="events">
      <div className="section-title"><h3>Журнал подій</h3><span>останні {events.length}</span></div>
      <div className="event-list">{events.length === 0 ? <div className="empty">Подій поки немає.</div> : events.map(event =>
        <div className="event" key={event.id}><i className={event.level} /><time>{new Date(event.created_at).toLocaleString('uk-UA')}</time>
          <strong>{event.kind.replaceAll('_', ' ')}</strong><span>{event.message}</span></div>)}</div>
    </section>
  </main>;
}

function OrderRow({order}: {order: OrderDetails}) {
  const filled = Number(order.executed_quantity) > 0;
  return <details className={`order-row ${order.status.toLowerCase()}`}>
    <summary>
      <span className={`order-side ${order.side.toLowerCase()}`}>{order.side}</span>
      <strong>{order.symbol}</strong>
      <span className="order-price">{formatNumber(order.quantity, 8)} @ {formatNumber(order.price, 8)}</span>
      <span className={`order-status ${filled ? 'has-fill' : ''}`}>{orderLabels[order.status] || order.status}</span>
      <time>{new Date(order.created_at).toLocaleString('uk-UA')}</time>
    </summary>
    <div className="order-details">
      <dl><div><dt>Exchange order ID</dt><dd title={order.exchange_order_id}>{order.exchange_order_id}</dd></div>
        <div><dt>Client order ID</dt><dd title={order.client_order_id}>{order.client_order_id}</dd></div>
        <div><dt>Статус циклу</dt><dd>{order.cycle_status}</dd></div>
        <div><dt>Сума ордера</dt><dd>{formatNumber(order.quote_value, 8)} {order.quote_asset}</dd></div>
        <div><dt>Виконано</dt><dd>{formatNumber(order.executed_quantity, 8)} / {formatNumber(order.quantity, 8)} {order.base_asset}</dd></div>
        <div><dt>Відсоток виконання</dt><dd>{formatNumber(order.execution_pct, 2)}%</dd></div>
        <div><dt>Останнє оновлення</dt><dd>{new Date(order.updated_at).toLocaleString('uk-UA')}</dd></div></dl>
      <h4>Фактичні виконання ({order.fills.length})</h4>
      {order.fills.length === 0 ? <p className="no-fills">Біржа ще не повернула виконань для цього ордера.</p> :
        <div className="table-scroll"><table><thead><tr><th>Trade ID</th><th>Час</th><th>Ціна</th>
          <th>Кількість</th><th>Обсяг</th><th>Обсяг, USDT</th><th>Комісія</th></tr></thead><tbody>
          {order.fills.map(fill => <tr key={fill.id}><td title={fill.exchange_trade_id}>{fill.exchange_trade_id}</td>
            <td>{new Date(fill.executed_at).toLocaleString('uk-UA')}</td><td>{formatNumber(fill.price, 8)}</td>
            <td>{formatNumber(fill.quantity, 8)}</td><td>{formatNumber(fill.quote_quantity, 8)} {order.quote_asset}</td>
            <td>{fill.quote_quantity_usdt === null ? '—' : `${formatNumber(fill.quote_quantity_usdt, 2)} USDT`}</td>
            <td>{formatNumber(fill.commission, 8)} {fill.commission_asset}</td></tr>)}</tbody></table></div>}
    </div>
  </details>;
}

function Stat({label, value, tone=''}: {label:string; value:string; tone?:string}) {
  return <div className={`stat ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function SymbolPicker({value, onSelect}: {value:string; onSelect:(item:ExchangeSymbol)=>void}) {
  const [query, setQuery] = useState(value);
  const [options, setOptions] = useState<ExchangeSymbol[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);

  useEffect(() => setQuery(value), [value]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.symbols(query);
        if (!cancelled) { setOptions(data); setActive(0); }
      } catch { if (!cancelled) setOptions([]); }
      finally { if (!cancelled) setLoading(false); }
    }, 200);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [query, open]);

  function choose(item: ExchangeSymbol) {
    onSelect(item); setQuery(item.symbol); setOpen(false);
  }

  function keys(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); setActive(v => Math.min(v + 1, options.length - 1)); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive(v => Math.max(v - 1, 0)); }
    if (event.key === 'Enter' && open && options[active]) { event.preventDefault(); choose(options[active]); }
    if (event.key === 'Escape') setOpen(false);
  }

  return <label className="symbol-picker"><span>Тікер</span>
    <div className="combo-wrap">
      <input role="combobox" aria-label="Тікер" aria-expanded={open} aria-controls="symbol-options"
        autoComplete="off" value={query} onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onChange={event => { setQuery(event.target.value.toUpperCase()); setOpen(true); }} onKeyDown={keys} />
      <i className="chevron">⌄</i>
      {open && <div className="symbol-menu" id="symbol-options" role="listbox">
        {loading ? <div className="combo-note">Завантаження…</div> : options.length === 0 ?
          <div className="combo-note">Пари не знайдено</div> : options.map((item, index) =>
          <button type="button" role="option" aria-selected={item.symbol === value} className={index === active ? 'active' : ''}
            key={item.symbol} onMouseDown={event => event.preventDefault()} onClick={() => choose(item)}>
            <strong>{item.base_asset}<em>/{item.quote_asset}</em></strong><small>{item.symbol}</small>
          </button>)}
      </div>}
    </div>
  </label>;
}

function Field({label, value, onChange, type='text', readOnly=false}: {label: string; value: string | number; onChange?: (v:string)=>void; type?:string; readOnly?:boolean}) {
  return <label><span>{label}</span><input required type={type} step={type === 'number' ? 'any' : undefined} value={value}
    readOnly={readOnly} className={readOnly ? 'readonly' : ''} onChange={e => onChange?.(e.target.value)} /></label>;
}

function PairCard({runtime, busy, onAct, onEdit}: {
  runtime: Runtime; busy: string; onAct: (id:string, a:'start'|'stop')=>void; onEdit:(r:Runtime)=>void;
}) {
  const p = runtime.pair;
  const baseWarning = runtime.base_free !== null && Number(runtime.base_free) <= Number(p.base_balance_trigger);
  const quoteWarning = runtime.quote_free !== null && Number(runtime.quote_free) <= Number(p.quote_balance_trigger);
  const midpoint = runtime.bid !== null && runtime.ask !== null
    ? (Number(runtime.bid) + Number(runtime.ask)) / 2 : null;
  const baseValue = midpoint !== null && runtime.base_free !== null
    ? Number(runtime.base_free) * midpoint : null;
  const quoteValue = runtime.quote_free !== null ? Number(runtime.quote_free) : null;
  const portfolioValue = baseValue !== null && quoteValue !== null ? baseValue + quoteValue : null;
  const baseShare = portfolioValue !== null && portfolioValue > 0 && baseValue !== null
    ? baseValue / portfolioValue * 100 : null;
  const quoteShare = portfolioValue !== null && portfolioValue > 0 && quoteValue !== null
    ? quoteValue / portfolioValue * 100 : null;
  return <article className={`pair-card ${p.status}`}>
    <div className="pair-head"><div><span className="exchange">{p.exchange}</span><h3>{p.base_asset}<em>/{p.quote_asset}</em></h3></div>
      <span className="status"><i />{labels[p.status] || p.status}</span></div>
    <div className="quote"><div><span>BID</span><strong>{formatNumber(runtime.bid, p.price_precision, true)}</strong></div>
      <div><span>ASK</span><strong>{formatNumber(runtime.ask, p.price_precision, true)}</strong></div></div>
    <div className="irb-row"><span>Індикатор руху балансу</span><div>
      <b>{p.irb > 0 ? '+' : ''}{p.irb}</b></div></div>
    <div className="balance-grid">
      <div className={baseWarning ? 'warn' : ''}><span>Баланс {p.base_asset}</span><strong>{formatNumber(runtime.base_free, p.quantity_precision)}</strong>
        {baseValue !== null && <div className="valuation">≈ {formatNumber(baseValue, p.price_precision)} {p.quote_asset}
          {baseShare !== null && <b>{formatNumber(baseShare, 1)}%</b>}</div>
        }
        <small>trigger {formatNumber(p.base_balance_trigger, p.quantity_precision)} · limit {formatNumber(p.base_balance_limit, p.quantity_precision)}</small></div>
      <div className={quoteWarning ? 'warn' : ''}><span>Баланс {p.quote_asset}</span><strong>{formatNumber(runtime.quote_free, p.price_precision)}</strong>
        {quoteValue !== null && <div className="valuation">≈ {formatNumber(quoteValue, p.price_precision)} {p.quote_asset}
          {quoteShare !== null && <b>{formatNumber(quoteShare, 1)}%</b>}</div>
        }
        <small>trigger {formatNumber(p.quote_balance_trigger, p.price_precision)} · limit {formatNumber(p.quote_balance_limit, p.price_precision)}</small></div>
    </div>
    {baseShare !== null && quoteShare !== null && <div className="allocation" aria-label={`Розподіл балансу: ${p.base_asset} ${formatNumber(baseShare, 1)}%, ${p.quote_asset} ${formatNumber(quoteShare, 1)}%`}>
      <i style={{width: `${baseShare}%`}} /><span /></div>}
    <dl><div><dt>Лот</dt><dd>{formatNumber(p.lot_quote, p.price_precision)} {p.quote_asset}</dd></div><div><dt>Спред</dt><dd>{formatNumber(p.spread_pct, 6)}%</dd></div>
      <div><dt>Зміщення</dt><dd>{formatNumber(p.order_offset_pct, 6)}%</dd></div><div><dt>Red line</dt><dd>{formatNumber(p.red_line_pct, 6)}%</dd></div>
      <div><dt>Ордери</dt><dd>{runtime.open_orders}</dd></div><div><dt>Пауза</dt><dd>{p.pause_minutes} хв</dd></div></dl>
    {p.last_error && <p className="pair-error">{p.last_error}</p>}
    <div className="actions"><button className={p.enabled ? 'danger' : 'primary'} disabled={busy.startsWith(p.id)}
      onClick={() => onAct(p.id, p.enabled ? 'stop' : 'start')}>{p.enabled ? 'Зупинити' : 'Запустити'}</button>
      <button className="secondary" disabled={p.enabled || busy.startsWith(p.id)} onClick={() => onEdit(runtime)}>Редагувати</button></div>
  </article>;
}

export default App;

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api';
import type { AnalyticsReport, Runtime } from './types';

const EMPTY_REPORT: AnalyticsReport = {
  date_from: null, date_to: new Date().toISOString(), granularity: 'day',
  totals: {
    successful_trades: 0, unsuccessful_trades: 0, total_trades: 0,
    success_rate_pct: '0', by_quote_asset: [], pairs: [],
  },
  periods: [],
};

function formatNumber(value: string | number, precision = 2) {
  return Number(value).toLocaleString('en-US', {maximumFractionDigits: precision});
}

function periodLabel(value: string, granularity: string) {
  const date = new Date(value);
  if (granularity === 'month') return date.toLocaleDateString('uk-UA', {month: 'long', year: 'numeric'});
  if (granularity === 'week') return `Тиждень від ${date.toLocaleDateString('uk-UA')}`;
  return date.toLocaleDateString('uk-UA', {day: '2-digit', month: 'short', year: 'numeric'});
}

function startDate(range: string): string | undefined {
  if (range === 'all') return undefined;
  const days = Number(range);
  const date = new Date();
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCDate(date.getUTCDate() - days + 1);
  return date.toISOString();
}

export default function AnalyticsPage() {
  const [pairs, setPairs] = useState<Runtime[]>([]);
  const [report, setReport] = useState<AnalyticsReport>(EMPTY_REPORT);
  const [range, setRange] = useState('30');
  const [granularity, setGranularity] = useState('day');
  const [pairId, setPairId] = useState('all');
  const [paperProfit, setPaperProfit] = useState(() => localStorage.getItem('paper-profit') === 'true');
  const [dryRun, setDryRun] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [health, pairData, data] = await Promise.all([
        api.health(), api.pairs(),
        api.analytics({
          dateFrom: startDate(range), dateTo: new Date().toISOString(),
          granularity, pairId, paperProfit,
        }),
      ]);
      setDryRun(health.dry_run);
      setPairs(pairData);
      setReport(data);
      setError('');
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }, [range, granularity, pairId, paperProfit]);

  useEffect(() => { refresh(); }, [refresh]);

  const totalVolume = report.totals.by_quote_asset.reduce(
    (sum, bucket) => sum + Number(bucket.trading_volume_usdt), 0,
  );
  const maxVolume = Math.max(1, ...report.periods.map(item => Number(item.trading_volume_usdt)));
  const maxTrades = Math.max(1, ...report.periods.map(item => item.total_trades));
  const periodRows = useMemo(() => [...report.periods].reverse(), [report.periods]);

  return <main>
    <header>
      <div><span className="eyebrow">MEXC · SPOT</span><h1>Inventory Market Maker</h1></div>
      <div className="header-actions">
        <nav aria-label="Основна навігація"><a href="/">Панель</a><a href="/analytics" className="active">Аналітика</a></nav>
        <div className={`mode ${dryRun ? 'paper' : 'live'}`}><i />{dryRun ? 'DRY RUN' : 'LIVE TRADING'}</div>
      </div>
    </header>

    {error && <div className="error page-error"><span>{error}</span><button onClick={() => setError('')}>×</button></div>}

    <section className="analytics-hero">
      <div><p className="kicker">Аналіз результатів</p><h2>Торгова картина в часі.</h2>
        <p>Прибуток, комісії, обсяг та ефективність — у розрізі періодів і торгових пар.</p></div>
      <a className="secondary back-link" href="/">← До панелі</a>
    </section>

    <section className="analytics-filters" aria-label="Фільтри аналітики">
      <label><span>Період</span><select value={range} onChange={event => setRange(event.target.value)}>
        <option value="7">7 днів</option><option value="30">30 днів</option>
        <option value="90">90 днів</option><option value="365">12 місяців</option>
        <option value="all">Весь час</option>
      </select></label>
      <label><span>Групування</span><select value={granularity} onChange={event => setGranularity(event.target.value)}>
        <option value="day">По днях</option><option value="week">По тижнях</option>
        <option value="month">По місяцях</option>
      </select></label>
      <label><span>Торгова пара</span><select value={pairId} onChange={event => setPairId(event.target.value)}>
        <option value="all">Усі пари</option>
        {pairs.map(runtime => <option key={runtime.pair.id} value={runtime.pair.id}>{runtime.pair.symbol}</option>)}
      </select></label>
      <label className="pp-toggle analytics-toggle" title="Не враховувати RED_LINE як зафіксований збиток">
        <span>Paper profit</span><div><input type="checkbox" checked={paperProfit} onChange={event => {
          setPaperProfit(event.target.checked);
          localStorage.setItem('paper-profit', String(event.target.checked));
        }} /><i /><b>ПП</b></div>
      </label>
    </section>

    <section className={`analytics-content ${loading ? 'is-loading' : ''}`}>
      <div className="stats-grid analytics-summary">
        <Metric label="Закриті цикли" value={String(report.totals.total_trades)} />
        <Metric label="Успішність" value={`${Number(report.totals.success_rate_pct).toFixed(1)}%`} />
        <Metric label="Обсяг" value={`${formatNumber(totalVolume)} USDT`} />
        <Metric label="Комісії" value={report.totals.by_quote_asset.length === 1
          ? `${formatNumber(report.totals.by_quote_asset[0].commission, 6)} ${report.totals.by_quote_asset[0].quote_asset}`
          : `${report.totals.by_quote_asset.length} активи`} />
      </div>

      {report.totals.by_quote_asset.length > 0 && <div className="profit-grid analytics-profit">
        {report.totals.by_quote_asset.map(bucket => <article key={bucket.quote_asset}>
          <div><span>Чистий результат у {bucket.quote_asset}</span>
            <strong className={Number(bucket.net_profit) >= 0 ? 'positive' : 'negative'}>
              {formatNumber(bucket.net_profit, 8)} {bucket.quote_asset}</strong></div>
          <dl><div><dt>Валовий</dt><dd>{formatNumber(bucket.gross_profit, 8)}</dd></div>
            <div><dt>Комісії</dt><dd>{formatNumber(bucket.commission, 8)}</dd></div></dl>
        </article>)}
      </div>}

      <div className="analytics-section">
        <div className="section-title"><h3>Динаміка за періодами</h3><span>{report.periods.length} періодів</span></div>
        {periodRows.length === 0 ? <div className="empty">За обраний період немає закритих торгових циклів.</div> :
          <div className="timeline-list">{periodRows.map(item => <article className="timeline-row" key={item.period_start}>
            <div className="timeline-label"><strong>{periodLabel(item.period_start, granularity)}</strong>
              <span>{item.total_trades} циклів · {Number(item.success_rate_pct).toFixed(1)}% вдало</span></div>
            <div className="bar-column"><span>Обсяг {formatNumber(item.trading_volume_usdt)} USDT</span>
              <i><b style={{width: `${Number(item.trading_volume_usdt) / maxVolume * 100}%`}} /></i></div>
            <div className="bar-column trades"><span>{item.total_trades} циклів</span>
              <i><b style={{width: `${item.total_trades / maxTrades * 100}%`}} /></i></div>
            <div className="period-profit">{item.by_quote_asset.map(bucket =>
              <span key={bucket.quote_asset} className={Number(bucket.net_profit) >= 0 ? 'positive' : 'negative'}>
                {Number(bucket.net_profit) >= 0 ? '+' : ''}{formatNumber(bucket.net_profit, 6)} {bucket.quote_asset}
              </span>)}</div>
          </article>)}</div>}
      </div>

      <div className="analytics-section">
        <div className="section-title"><h3>Результати за торговими парами</h3><span>{report.totals.pairs.length} пар</span></div>
        {report.totals.pairs.length === 0 ? <div className="empty">Немає даних для порівняння пар.</div> :
          <div className="table-scroll"><table><thead><tr><th>Пара</th><th>Цикли</th><th>Успішність</th>
            <th>Обсяг, USDT</th><th>Валовий результат</th><th>Комісії</th><th>Чистий результат</th>
          </tr></thead><tbody>{report.totals.pairs.map(pair => <tr key={pair.pair_id}>
            <td><strong>{pair.symbol}</strong></td><td>{pair.total_trades}</td>
            <td>{Number(pair.success_rate_pct).toFixed(1)}%</td>
            <td>{formatNumber(pair.trading_volume_usdt)} USDT</td>
            <td>{formatNumber(pair.gross_profit, 8)} {pair.quote_asset}</td>
            <td>{formatNumber(pair.commission, 8)} {pair.quote_asset}</td>
            <td className={Number(pair.net_profit) >= 0 ? 'positive' : 'negative'}>
              {formatNumber(pair.net_profit, 8)} {pair.quote_asset}</td>
          </tr>)}</tbody></table></div>}
      </div>
    </section>
  </main>;
}

function Metric({label, value}: {label: string; value: string}) {
  return <div className="stat"><span>{label}</span><strong>{value}</strong></div>;
}

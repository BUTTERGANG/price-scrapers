import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { useFetch } from '../lib/hooks';
import { API_BASE, THIRTY_MIN, fmtPct, chartTheme } from '../lib/utils';
import { BLUE, INDIGO, GREEN, GREEN_DARK, AMBER, AMBER_DARK, PURPLE } from '../lib/colors';
import { Spinner, SummaryCard, DataFreshnessBar } from './Shared';

export default function DashboardView({ onNavigate }) {
  const { data, loading, error, lastFetched } = useFetch(`${API_BASE}/dashboard`, THIRTY_MIN);
  const ct = chartTheme();

  if (loading) return <Spinner />;
  if (error) return <div className="error">Error: {error}</div>;
  if (!data) return null;

  const { summary, pulse, activity } = data;

  return (
    <div className="dashboard">
      <div className="summary-grid">
        <SummaryCard
          label="Products Tracked"
          value={summary.unique_products?.toLocaleString()}
          icon="📦"
          accent={`linear-gradient(90deg, ${BLUE}, ${INDIGO})`}
        />
        <SummaryCard
          label="Active Deals"
          value={summary.active_deals?.toLocaleString()}
          color="var(--green)"
          icon="🏷️"
          accent={`linear-gradient(90deg, ${GREEN}, ${GREEN_DARK})`}
        />
        <SummaryCard
          label="Avg Savings"
          value={fmtPct(summary.avg_savings_pct)}
          color={AMBER}
          icon="💰"
          accent={`linear-gradient(90deg, ${AMBER}, ${AMBER_DARK})`}
        />
        <SummaryCard
          label="Retailers"
          value={summary.retailer_count}
          color="var(--accent)"
          icon="🏪"
          accent={`linear-gradient(90deg, ${PURPLE}, ${INDIGO})`}
        />
      </div>

      {activity && activity.length > 0 && (
        <div className="chart-card">
          <h3>Scrape Activity — Last 14 Days</h3>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activity} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <defs>
                <linearGradient id="gradRecords" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={BLUE} stopOpacity={0.35} />
                  <stop offset="95%" stopColor={BLUE} stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gradRuns" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={PURPLE} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={PURPLE} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
              <XAxis dataKey="day" tick={{ fill: ct.tick, fontSize: 11 }} tickFormatter={v => v.slice(5)} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: ct.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: ct.tooltipBg, border: `1px solid ${ct.tooltipBorder}`, borderRadius: 10, color: ct.tooltipColor, fontSize: 13 }}
                cursor={{ stroke: ct.cursorStroke, strokeWidth: 1 }}
              />
              <Area type="monotone" dataKey="records" stroke={BLUE} strokeWidth={2} fill="url(#gradRecords)" name="Records" dot={false} />
              <Area type="monotone" dataKey="runs" stroke={PURPLE} strokeWidth={2} fill="url(#gradRuns)" name="Runs" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {pulse && (pulse.biggest_drops?.length > 0 || pulse.biggest_increases?.length > 0) && (
        <div className="pulse-section">
          <div className="pulse-section-header">
            <span style={{ fontSize: '1rem' }}>⚡</span>
            <h3>Market Pulse</h3>
          </div>
          <div className="pulse-grid">
            {pulse.biggest_drops?.length > 0 && (
              <div className="pulse-col">
                <div className="pulse-col-header">
                  <span>📉</span>
                  <h4 className="pulse-drops-title">Biggest Drops</h4>
                </div>
                {pulse.biggest_drops.slice(0, 5).map((item, i) => (
                  <div key={i} className="pulse-item drop-item">
                    <div className="pulse-name">{item.name}</div>
                    <div className="pulse-detail">
                      <span className="pulse-retailer">{item.retailer}</span>
                      <span className="pulse-change drop">{fmtPct(item.change_pct)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {pulse.biggest_increases?.length > 0 && (
              <div className="pulse-col">
                <div className="pulse-col-header">
                  <span>📈</span>
                  <h4 className="pulse-increases-title">Biggest Increases</h4>
                </div>
                {pulse.biggest_increases.slice(0, 5).map((item, i) => (
                  <div key={i} className="pulse-item increase-item">
                    <div className="pulse-name">{item.name}</div>
                    <div className="pulse-detail">
                      <span className="pulse-retailer">{item.retailer}</span>
                      <span className="pulse-change increase">+{fmtPct(Math.abs(item.change_pct))}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="dashboard-actions">
        <button className="action-btn" onClick={() => onNavigate('deals')}>🏷️ Browse Deals</button>
        <button className="action-btn" onClick={() => onNavigate('compare')}>⚖️ Compare Prices</button>
        <button className="action-btn" onClick={() => onNavigate('departments')}>🗂️ Browse Departments</button>
      </div>
      <DataFreshnessBar lastFetched={lastFetched} />
    </div>
  );
}

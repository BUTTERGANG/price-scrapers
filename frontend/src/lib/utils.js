// Shared constants and formatting helpers.

export const API_BASE = '/api';

export const timeAgo = (ts) => {
  if (!ts) return 'Never';
  const diff = Date.now() - new Date(ts).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

// Bucket a scrape timestamp into a freshness level for color-coding:
// fresh (<24h), aging (1–7d), stale (>7d), unknown (no timestamp).
export const freshnessLevel = (ts) => {
  if (!ts) return 'unknown';
  const hours = (Date.now() - new Date(ts).getTime()) / 3600000;
  if (hours < 24) return 'fresh';
  if (hours < 24 * 7) return 'aging';
  return 'stale';
};

export const fmtPrice = (v) => v != null ? `$${Number(v).toFixed(2)}` : '--';
export const fmtPct = (v) => v != null ? `${Number(v).toFixed(1)}%` : '--';
export const fmtUnitPrice = (value, canonical) => {
  if (!value || !canonical) return '--';
  const formatted = value < 0.1 ? value.toFixed(4) : value.toFixed(2);
  return `$${formatted} ${canonical.replace('per_', '/')}`;
};

export const CHART_COLORS = ['#3b82f6', '#8b5cf6', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

export const RETAILER_COLORS = {
  'kroger':        '#0072CE',
  'meijer':        '#e01933',
  'walmart':       '#0071CE',
  'aldi':          '#ef7c00',
  'target':        '#cc0000',
  'whole foods':   '#00674b',
  'fresh thyme':   '#5aab19',
  'costco':        '#e31837',
  'giant eagle':   '#008000',
  'fresh market':  '#8b4513',
  'gfs':           '#1a5276',
  'needlers':      '#6a0dad',
  'harvest market':'#2e7d32',
  'gordon food':   '#1a5276',
};

export const getRetailerColor = (name) => {
  if (!name) return '#64748b';
  const key = name.toLowerCase();
  for (const [k, v] of Object.entries(RETAILER_COLORS)) {
    if (key.includes(k)) return v;
  }
  return '#64748b';
};

export const DEPT_ICONS = {
  'Produce': '🥦', 'Fruits': '🍎', 'Vegetables': '🥕', 'Dairy': '🥛', 'Eggs': '🥚',
  'Meat': '🥩', 'Seafood': '🐟', 'Bakery': '🍞', 'Frozen': '🧊', 'Beverages': '🧃',
  'Snacks': '🍿', 'Pantry': '🥫', 'Deli': '🧀', 'Cereal': '🌾', 'Pasta': '🍝',
  'Canned': '🥫', 'Cleaning': '🧹', 'Personal Care': '🧴', 'Baby': '🍼',
  'Pet': '🐾', 'Organic': '🌿', 'International': '🌍', 'Dips': '🫙',
};

export const getDeptIcon = (name) => {
  if (!name) return '🛒';
  for (const [key, icon] of Object.entries(DEPT_ICONS)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return icon;
  }
  return '🛒';
};

export const THIRTY_MIN = 30 * 60 * 1000;
export const FIVE_MIN = 5 * 60 * 1000;

// Buy/wait signal for a single item's price history, in the spirit of
// camelcamelcamel: is the current price near the historical floor (buy),
// near/above the average (wait), or too little history to say yet.
export const priceSignal = (current, min, avg, sampleCount) => {
  if (current == null || sampleCount < 3) {
    return { tone: 'neutral', icon: '—', label: 'Not enough history yet' };
  }
  if (current <= min * 1.03) {
    return { tone: 'buy', icon: '🔥', label: 'Near all-time low — great time to buy' };
  }
  if (current <= avg * 0.95) {
    return { tone: 'buy', icon: '✓', label: 'Below average — good time to buy' };
  }
  if (current >= avg * 1.08) {
    return { tone: 'wait', icon: '⏳', label: 'Above average — may be worth waiting' };
  }
  return { tone: 'neutral', icon: '•', label: 'Typical price for this item' };
};

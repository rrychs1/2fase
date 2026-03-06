/**
 * Trading Bot Dashboard — Client-side logic
 * Auto-refreshes every 10 seconds, renders Chart.js equity chart + tables.
 */

const REFRESH_MS = 10_000;
let equityChart = null;

// ─────────────────────────── API fetch helpers ───────────────
async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        return await res.json();
    } catch (e) {
        console.warn(`Fetch failed: ${url}`, e);
        return null;
    }
}

// ─────────────────────────── Animations ──────────────────────
function animateValue(id, start, end, duration, isCurrency = true) {
    const obj = document.getElementById(id);
    if (!obj) return;

    // Skip animation if values are the same
    const currentVal = parseFloat(obj.getAttribute('data-value') || '0');
    if (Math.abs(currentVal - end) < 0.01) return;
    obj.setAttribute('data-value', end);

    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const val = progress * (end - start) + start;

        if (isCurrency) {
            obj.textContent = `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        } else {
            obj.textContent = Math.floor(val).toLocaleString();
        }

        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}

// ─────────────────────────── Status header ───────────────────
function renderStatus(data) {
    const badge = document.getElementById('status-badge');
    const iterationEl = document.getElementById('iteration');
    const modeEl = document.getElementById('mode');

    if (!data || data.status === undefined) {
        badge.className = 'status-badge offline';
        badge.innerHTML = '<span class="status-dot"></span> Disconnected';
        return;
    }

    // Senior Hardening: Use is_active from backend + local secondary check
    const lastLoop = new Date(data.last_loop);
    const localStale = (Date.now() - lastLoop.getTime()) > 120_000;
    const isActive = data.is_active && !localStale;

    if (isActive) {
        badge.className = 'status-badge';
        badge.innerHTML = '<span class="status-dot"></span> Running';
    } else {
        badge.className = 'status-badge offline';
        badge.innerHTML = `<span class="status-dot"></span> ${data.status === 'Offline' ? 'Stopped' : 'Stalled'}`;
    }

    lastLoopEl.textContent = lastLoop.toLocaleTimeString() || '--';
    if (iterationEl) iterationEl.textContent = data.iteration || '0';
    if (modeEl) modeEl.textContent = data.mode || 'Unknown';

    // Phase 19: Health Rendering
    renderHealth(data);
}

function renderHealth(data) {
    const exchangeEl = document.getElementById('health-exchange');
    const telegramEl = document.getElementById('health-telegram');
    const errorCont = document.getElementById('last-error-content');

    if (!data) return;

    // Exchange Status
    if (exchangeEl) {
        const exStatus = data.exchange_status || 'Unknown';
        exchangeEl.textContent = exStatus;
        exchangeEl.className = `badge ${exStatus === 'Connected' ? 'healthy' : 'critical'}`;
    }

    // Telegram Status
    if (telegramEl) {
        const telHealthy = data.telegram_healthy !== false;
        telegramEl.textContent = telHealthy ? 'Healthy' : 'Error';
        telegramEl.className = `badge ${telHealthy ? 'healthy' : 'critical'}`;
    }

    // Loop Status
    const loopEl = document.getElementById('health-loop');
    if (loopEl) {
        const lastLoop = new Date(data.last_loop);
        const localStale = (Date.now() - lastLoop.getTime()) > 120_000;
        const isActive = data.is_active && !localStale;
        loopEl.textContent = isActive ? 'Active' : (data.status === 'Offline' ? 'Stopped' : 'Stalled');
        loopEl.className = `badge ${isActive ? 'healthy' : 'critical'}`;
    }

    // Phase 22: Detailed Operational Status
    const botStatus = data.bot_status || {};
    const opTrading = document.getElementById('op-trading');
    const opPaper = document.getElementById('op-paper');
    const opReason = document.getElementById('op-reason');

    if (opTrading) {
        const trading = botStatus.trading_enabled !== false;
        opTrading.textContent = trading ? 'ENABLED' : 'BLOCKED';
        opTrading.className = `badge ${trading ? 'healthy' : 'critical'}`;
    }
    if (opPaper) {
        const paper = botStatus.paper_trading_enabled === true;
        opPaper.textContent = paper ? 'YES' : 'LIVE';
        opPaper.className = `badge ${paper ? 'warning' : 'healthy'}`;
    }
    if (opReason) {
        opReason.textContent = botStatus.last_change_reason || 'System operational';
        opReason.style.color = botStatus.trading_enabled === false ? 'var(--accent-red)' : 'var(--accent-green)';
    }

    // Last Error Display
    if (errorCont) {
        if (data.last_error) {
            const err = data.last_error;
            const errTime = new Date(err.ts).toLocaleTimeString();
            errorCont.innerHTML = `
                <strong>${err.type}</strong>: ${err.msg}
                <span class="error-time">Ocurrido a las ${errTime}</span>
            `;
            errorCont.style.color = 'var(--accent-red)';
        } else {
            errorCont.innerHTML = '<span class="empty-state">No critical errors reported in this session.</span>';
        }
    }
}

// ─────────────────────────── KPI Cards ───────────────────────
function renderKPIs(data) {
    if (!data) return;

    const balance = data.balance || 0;
    const equity = data.equity || balance;
    const unrealizedPnL = equity - balance;
    const totalPnL = data.total_pnl || 0;

    // Use animated counting for main metrics
    animateValue('kpi-balance', parseFloat(document.getElementById('kpi-balance')?.getAttribute('data-value') || '0'), balance, 800);
    animateValue('kpi-equity', parseFloat(document.getElementById('kpi-equity')?.getAttribute('data-value') || '0'), equity, 800);
    animateValue('kpi-total-pnl', parseFloat(document.getElementById('kpi-total-pnl')?.getAttribute('data-value') || '0'), totalPnL, 800);

    // Static updates for smaller metrics
    const setStat = (id, value, cssClass = '') => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
            el.className = `kpi-value ${cssClass}`;
        }
    };

    setStat('kpi-unrealized', `${unrealizedPnL >= 0 ? '+' : ''}$${unrealizedPnL.toFixed(2)}`,
        unrealizedPnL >= 0 ? 'positive' : 'negative');
    setStat('kpi-trades', data.total_trades || 0, 'neutral');
    setStat('kpi-winrate', `${data.win_rate || 0}%`,
        (data.win_rate || 0) >= 50 ? 'positive' : (data.win_rate > 0 ? 'negative' : 'neutral'));

    // Update color for equity and PnL
    document.getElementById('kpi-equity').className = `kpi-value ${unrealizedPnL >= 0 ? 'positive' : 'negative'}`;
    document.getElementById('kpi-total-pnl').className = `kpi-value ${totalPnL >= 0 ? 'positive' : 'negative'}`;
}

// ─────────────────────────── Equity Chart ────────────────────
function renderEquityChart(data) {
    if (!data || data.length === 0) return;

    const canvas = document.getElementById('equity-chart');
    const ctx = canvas.getContext('2d');

    // Deduplicate by unique timestamp
    const seen = new Set();
    const unique = data.filter(d => {
        const key = d.ts + d.symbol;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });

    // Aggregate by timestamp (take max equity across symbols)
    const byTs = {};
    unique.forEach(d => {
        if (!byTs[d.ts] || d.equity > byTs[d.ts].equity) {
            byTs[d.ts] = d;
        }
    });
    const points = Object.values(byTs).slice(-200);

    const labels = points.map(d => {
        const dt = new Date(d.ts);
        return dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    });
    const values = points.map(d => d.equity);

    if (equityChart) {
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.update('none');
        return;
    }

    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, 'rgba(0,180,216,0.25)');
    gradient.addColorStop(1, 'rgba(0,180,216,0.02)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Equity (USDT)',
                data: values,
                borderColor: '#00b4d8',
                borderWidth: 2,
                backgroundColor: gradient,
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHitRadius: 8,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(22,27,34,0.95)',
                    titleColor: '#e6edf3',
                    bodyColor: '#8b949e',
                    borderColor: 'rgba(48,54,61,0.6)',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: ctx => `$${ctx.raw.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(48,54,61,0.3)', drawBorder: false },
                    ticks: { color: '#484f58', maxTicksLimit: 10, font: { size: 11 } },
                },
                y: {
                    grid: { color: 'rgba(48,54,61,0.3)', drawBorder: false },
                    ticks: {
                        color: '#484f58', font: { size: 11 },
                        callback: v => `$${v.toLocaleString()}`
                    },
                }
            }
        }
    });
}

// ─────────────────────────── Positions Table ─────────────────
function renderPositions(positions) {
    const tbody = document.getElementById('positions-body');
    if (!positions || Object.keys(positions).length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No open positions</td></tr>';
        return;
    }
    tbody.innerHTML = Object.entries(positions).map(([symbol, pos]) => {
        const sideClass = pos.side === 'LONG' ? 'side-long' : 'side-short';
        return `<tr>
      <td>${symbol}</td>
      <td class="${sideClass}">${pos.side}</td>
      <td>${(pos.average_price || pos.entry_price || 0).toFixed(2)}</td>
      <td>${(pos.amount || 0).toFixed(4)}</td>
      <td>${pos.stop_loss ? pos.stop_loss.toFixed(2) : '—'} / ${pos.take_profit ? pos.take_profit.toFixed(2) : '—'}</td>
    </tr>`;
    }).join('');
}

// ─────────────────────────── Orders Table ────────────────────
function renderOrders(orders) {
    const tbody = document.getElementById('orders-body');
    const countEl = document.getElementById('orders-count');
    if (countEl) countEl.textContent = orders ? orders.length : 0;

    if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No pending orders</td></tr>';
        return;
    }
    // Show last 10
    tbody.innerHTML = orders.slice(-10).map(o => {
        const sideClass = o.side === 'LONG' ? 'side-long' : 'side-short';
        return `<tr>
      <td>${o.symbol}</td>
      <td class="${sideClass}">${o.side}</td>
      <td>${o.price.toFixed(2)}</td>
      <td class="badge badge-${o.type === 'grid' ? 'range' : 'trend'}">${o.type || 'limit'}</td>
    </tr>`;
    }).join('');
}

// ─────────────────────────── Trades Table ────────────────────
function renderTrades(history) {
    const tbody = document.getElementById('trades-body');
    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No trades yet</td></tr>';
        return;
    }
    tbody.innerHTML = history.slice().reverse().map(t => {
        const pnlClass = t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const dt = new Date(t.closed_at);
        return `<tr>
      <td>${t.symbol}</td>
      <td class="${t.side === 'LONG' ? 'side-long' : 'side-short'}">${t.side}</td>
      <td class="${pnlClass}">${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}</td>
      <td>${dt.toLocaleString()}</td>
    </tr>`;
    }).join('');
}

// ─────────────────────────── Regime Badges ───────────────────
function renderRegimeInfo(account) {
    const container = document.getElementById('regime-info');
    const regimes = account?.regimes || {};
    const prices = account?.prices || {};
    if (Object.keys(regimes).length === 0) {
        container.innerHTML = '<span class="empty-state">Waiting for data...</span>';
        return;
    }
    container.innerHTML = Object.entries(regimes).map(([symbol, regime]) => {
        const cls = regime === 'trend' ? 'badge-trend' : 'badge-range';
        const price = prices[symbol] ? `$${prices[symbol].toLocaleString()}` : '';
        return `<span style="margin-right:24px;display:inline-flex;align-items:center;gap:8px;">
      <strong>${symbol}</strong>
      <span class="badge ${cls}">${regime}</span>
      <span style="color:var(--text-muted);font-size:0.82rem;">${price}</span>
    </span>`;
    }).join('');
}

// ─────────────────────────── Alerts ──────────────────────────
function renderAlerts(alerts) {
    const body = document.getElementById('alerts-body');
    if (!alerts || alerts.length === 0) {
        body.innerHTML = '<tr><td colspan="3" class="empty-state">No recent notifications.</td></tr>';
        return;
    }

    body.innerHTML = alerts.map(a => {
        const time = new Date(a.ts).toLocaleTimeString();
        let levelClass = 'badge-neutral';
        if (a.level === 'ERROR' || a.level === 'CRITICAL') levelClass = 'badge-critical';
        else if (a.level === 'WARNING') levelClass = 'badge-warning';
        else if (a.level === 'TRADE') levelClass = 'badge-trend';

        return `<tr>
            <td><span class="text-dimmed">${time}</span></td>
            <td><span class="badge ${levelClass}">${a.level}</span></td>
            <td style="font-size: 0.9rem;">${a.msg}</td>
        </tr>`;
    }).join('');
}

// ─────────────────────────── Log Viewer ──────────────────────
function renderLogs(lines) {
    const viewer = document.getElementById('log-viewer');
    if (!lines || lines.length === 0) {
        viewer.innerHTML = '<div class="log-line">Waiting for logs...</div>';
        return;
    }
    const wasAtBottom = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 40;
    viewer.innerHTML = lines.map(l => {
        let cls = 'info';
        if (l.includes('ERROR') || l.includes('CRITICAL')) cls = 'error';
        else if (l.includes('WARNING')) cls = 'warning';
        return `<div class="log-line ${cls}">${escapeHtml(l)}</div>`;
    }).join('');
    if (wasAtBottom) viewer.scrollTop = viewer.scrollHeight;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─────────────────────────── Refresh Bar ─────────────────────
let refreshTimer = null;
function startRefreshBar() {
    const bar = document.getElementById('refresh-bar');
    bar.style.width = '0%';
    let progress = 0;
    clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
        progress += 100 / (REFRESH_MS / 100);
        bar.style.width = `${Math.min(progress, 100)}%`;
    }, 100);
}

// ─────────────────────────── Master refresh ──────────────────
async function refreshAll() {
    startRefreshBar();
    const [status, account, equity, logs, alerts] = await Promise.all([
        fetchJSON('/api/status'),
        fetchJSON('/api/account'),
        fetchJSON('/api/equity-history'),
        fetchJSON('/api/logs'),
        fetchJSON('/api/alerts')
    ]);

    renderStatus(status);
    renderKPIs(account);
    renderEquityChart(equity);
    renderPositions(account?.positions);
    renderOrders(account?.pending_orders);
    renderTrades(account?.history);
    renderRegimeInfo(account);
    renderLogs(logs);
    renderAlerts(alerts);
}

// ─────────────────────────── Init ────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    refreshAll();
    setInterval(refreshAll, REFRESH_MS);
});

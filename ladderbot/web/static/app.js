/**
 * LadderBot Dashboard — Frontend Logic
 *
 * Hash-based tab routing, API integration, Chart.js visualizations,
 * SSE live updates, and FanDuel odds verification flow.
 */

// ============================================================================
// State & Config
// ============================================================================

const API = '';  // Same origin
let charts = {};
let sseSource = null;

// ============================================================================
// Tab Routing
// ============================================================================

function initTabs() {
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            window.location.hash = target;
            switchTab(target);
        });
    });

    // Handle initial hash
    const hash = window.location.hash.replace('#', '') || 'picks';
    switchTab(hash);

    window.addEventListener('hashchange', () => {
        const hash = window.location.hash.replace('#', '') || 'picks';
        switchTab(hash);
    });
}

function switchTab(tabName) {
    // Hide all tab content
    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
    // Remove active from all tabs
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('tab-active'));

    // Show selected tab content
    const content = document.getElementById(`tab-${tabName}`);
    if (content) content.classList.remove('hidden');

    // Mark tab as active
    const tab = document.querySelector(`.tab[data-tab="${tabName}"]`);
    if (tab) tab.classList.add('tab-active');

    // Load data for the tab
    if (tabName === 'picks') loadPicks();
    else if (tabName === 'ladder') loadLadder();
    else if (tabName === 'performance') loadPerformance();
}

// ============================================================================
// API Helpers
// ============================================================================

async function apiFetch(path, options = {}) {
    try {
        const resp = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || resp.statusText);
        }
        return await resp.json();
    } catch (e) {
        console.error(`API error [${path}]:`, e);
        throw e;
    }
}

function formatOdds(odds) {
    if (odds === null || odds === undefined) return '--';
    return odds > 0 ? `+${odds}` : `${odds}`;
}

function formatMoney(amount) {
    if (amount === null || amount === undefined) return '--';
    const sign = amount >= 0 ? '+' : '';
    return `${sign}$${Math.abs(amount).toFixed(2)}`;
}

function formatDate(dateStr) {
    if (!dateStr) return '--';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' });
}

function formatPct(value) {
    if (value === null || value === undefined) return '--';
    return `${(value * 100).toFixed(1)}%`;
}

// ============================================================================
// Picks View
// ============================================================================

async function loadPicks() {
    const container = document.getElementById('picks-container');
    try {
        const data = await apiFetch('/api/picks/today');

        // Update date heading
        const heading = document.getElementById('picks-date-heading');
        const dateObj = new Date(data.date + 'T12:00:00');
        heading.textContent = `TODAY'S PICKS — ${dateObj.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}`;

        // Update header ladder info
        if (data.ladder) {
            const info = document.getElementById('header-ladder-info');
            info.textContent = `Step ${data.ladder.step} | $${data.ladder.bankroll?.toFixed(2) || '10.00'}`;
        }

        if (!data.picks || data.picks.length === 0) {
            container.innerHTML = `
                <div class="bg-gray-800 border border-gray-700 rounded-lg p-8 text-center">
                    <p class="text-gray-400 mb-2">No picks found for today.</p>
                    <p class="text-gray-500 text-sm">Picks are generated when the daily pipeline runs.</p>
                </div>`;
            return;
        }

        container.innerHTML = data.picks.map((p, i) => renderParlayCard(p, i + 1)).join('');
    } catch (e) {
        container.innerHTML = `
            <div class="bg-gray-800 border border-gray-700 rounded-lg p-8 text-center">
                <p class="text-gray-400 mb-2">No picks found for today.</p>
                <p class="text-gray-500 text-sm">Picks are generated when the daily pipeline runs.</p>
            </div>`;
    }
}

function renderParlayCard(parlay, rank) {
    const statusClass = parlay.placed ? 'card-placed' : parlay.skipped ? 'card-skipped' : '';
    const statusBadge = parlay.placed
        ? '<span class="text-xs bg-green-900 text-green-400 px-2 py-0.5 rounded-full">PLACED</span>'
        : parlay.skipped
        ? '<span class="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">SKIPPED</span>'
        : '';

    const confidenceColors = {
        'HIGH': 'text-green-400',
        'MEDIUM': 'text-yellow-400',
        'LOW': 'text-gray-400',
    };
    const confClass = confidenceColors[parlay.confidence] || 'text-gray-400';

    return `
    <div class="card relative bg-gray-800 border border-gray-700 rounded-lg p-5 ${statusClass}" id="parlay-${parlay.parlay_id}">
        <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
                <span class="text-sm font-bold text-gray-400">PARLAY #${rank}</span>
                ${statusBadge}
            </div>
            <div class="flex items-center gap-3">
                <span class="${confClass} text-xs font-semibold">${parlay.confidence}</span>
                <span class="text-lg font-bold text-white">${formatOdds(parlay.combined_odds)}</span>
            </div>
        </div>

        ${renderLeg(parlay.leg1, 1, parlay.parlay_id)}
        ${renderLeg(parlay.leg2, 2, parlay.parlay_id)}

        <!-- FD Parlay Odds Input -->
        <div class="mt-4 pt-4 border-t border-gray-700">
            <div class="flex items-center gap-4">
                <label class="text-xs text-gray-400 whitespace-nowrap">FD Parlay Odds:</label>
                <input type="number" id="fd-parlay-${parlay.parlay_id}"
                    class="odds-input bg-gray-700 border border-gray-600 rounded px-3 py-1.5 text-sm text-white w-24 text-center"
                    placeholder="${formatOdds(parlay.combined_odds)}"
                    value="${parlay.fd_parlay_odds || ''}"
                    ${parlay.placed || parlay.skipped ? 'disabled' : ''}>
                <button onclick="verifyOdds(${parlay.parlay_id})"
                    class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded transition-colors ${parlay.placed || parlay.skipped ? 'opacity-50 cursor-not-allowed' : ''}"
                    ${parlay.placed || parlay.skipped ? 'disabled' : ''}>
                    Verify
                </button>
            </div>
            <div id="verdict-${parlay.parlay_id}" class="mt-2 text-sm"></div>
        </div>

        <!-- Action Buttons -->
        ${!parlay.placed && !parlay.skipped ? `
        <div class="mt-4 flex gap-3">
            <button onclick="placePick(${parlay.parlay_id})"
                class="flex-1 bg-green-700 hover:bg-green-600 text-white text-sm font-medium py-2 px-4 rounded transition-colors">
                MARK AS PLACED
            </button>
            <button onclick="skipPick(${parlay.parlay_id})"
                class="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm font-medium py-2 px-4 rounded transition-colors">
                SKIP
            </button>
        </div>` : ''}
    </div>`;
}

function renderLeg(leg, num, parlayId) {
    if (!leg) {
        return `<div class="mb-3 pl-4 border-l-2 border-gray-700 py-2">
            <p class="text-sm text-gray-500">Leg ${num}: No data</p>
        </div>`;
    }

    let description;
    if (leg.market === 'h2h' || leg.market === 'moneyline') {
        // Moneyline: "San Antonio Spurs ML (-225)"
        description = `${leg.outcome} ML (${formatOdds(leg.odds_at_pick)})`;
    } else if (leg.market === 'totals') {
        // Totals: "Carolina Hurricanes vs St Louis Blues — OVER 5.5 (+120)"
        const side = (leg.outcome || '').toUpperCase();
        const matchup = `${leg.home_team} vs ${leg.away_team}`;
        const line = leg.total_line != null ? ` ${leg.total_line}` : '';
        description = `${matchup} — ${side}${line} (${formatOdds(leg.odds_at_pick)})`;
    } else {
        description = `${leg.outcome} (${formatOdds(leg.odds_at_pick)})`;
    }

    const edgeDisplay = leg.edge != null ? `${(leg.edge * 100).toFixed(1)}%` : '--';
    const modelDisplay = leg.model_prob != null ? `${(leg.model_prob * 100).toFixed(1)}%` : '--';
    const bookDisplay = leg.book_prob != null ? `${(leg.book_prob * 100).toFixed(1)}%` : '--';
    const sport = leg.sport ? leg.sport.toUpperCase() : '';

    return `
    <div class="mb-3 pl-4 border-l-2 border-gray-700 py-2">
        <div class="flex items-center justify-between">
            <div>
                <span class="text-xs text-indigo-400 font-medium">${sport}</span>
                <p class="text-sm font-medium text-white">LEG ${num}: ${description}</p>
                <p class="text-xs text-gray-400 mt-1">Model: ${modelDisplay} | Book (DK): ${bookDisplay}</p>
            </div>
            <div class="text-right">
                <span class="text-sm font-semibold ${parseFloat(edgeDisplay) > 0 ? 'text-green-400' : 'text-gray-400'}">
                    Edge: ${leg.edge >= 0 ? '+' : ''}${edgeDisplay}
                </span>
            </div>
        </div>
        <div class="flex items-center gap-3 mt-2">
            <label class="text-xs text-gray-500">FD Odds:</label>
            <input type="number" id="fd-leg${num}-${parlayId}"
                class="odds-input bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white w-20 text-center"
                placeholder="${formatOdds(leg.odds_at_pick)}"
                value="">
        </div>
    </div>`;
}

async function verifyOdds(parlayId) {
    const leg1Input = document.getElementById(`fd-leg1-${parlayId}`);
    const leg2Input = document.getElementById(`fd-leg2-${parlayId}`);
    const parlayInput = document.getElementById(`fd-parlay-${parlayId}`);
    const verdictEl = document.getElementById(`verdict-${parlayId}`);

    const fdLeg1 = parseInt(leg1Input?.value);
    const fdLeg2 = parseInt(leg2Input?.value);
    const fdParlay = parseInt(parlayInput?.value);

    if (isNaN(fdParlay)) {
        verdictEl.innerHTML = '<span class="text-yellow-400">Enter FD parlay odds to verify.</span>';
        return;
    }

    // Use leg inputs if provided, fallback to 0 (API will handle)
    const body = {
        fd_leg1_odds: isNaN(fdLeg1) ? 0 : fdLeg1,
        fd_leg2_odds: isNaN(fdLeg2) ? 0 : fdLeg2,
        fd_parlay_odds: fdParlay,
    };

    try {
        verdictEl.innerHTML = '<span class="text-gray-400"><span class="spinner inline-block mr-2"></span>Verifying...</span>';
        const result = await apiFetch(`/api/picks/${parlayId}/verify`, {
            method: 'POST',
            body: JSON.stringify(body),
        });

        const cls = result.still_plus_ev ? 'verdict-positive' : 'verdict-negative';
        const icon = result.still_plus_ev ? '&#10003;' : '&#9888;';
        verdictEl.innerHTML = `
            <div class="${cls} inline-block px-3 py-1.5 rounded text-sm font-medium">
                ${icon} ${result.verdict} &mdash; ${result.message}
            </div>
            <div class="text-xs text-gray-500 mt-1">
                DK: ${formatOdds(result.dk_parlay_odds)} | FD: ${formatOdds(result.fd_parlay_odds)} | Diff: ${result.odds_diff > 0 ? '+' : ''}${result.odds_diff}
            </div>`;
    } catch (e) {
        verdictEl.innerHTML = `<span class="text-red-400 text-sm">Error: ${e.message}</span>`;
    }
}

async function placePick(parlayId) {
    const parlayInput = document.getElementById(`fd-parlay-${parlayId}`);
    const actualOdds = parseInt(parlayInput?.value) || 0;

    // Prompt for stake (use current ladder bankroll as default)
    const stakeStr = prompt('Enter stake amount ($):', '10.00');
    if (stakeStr === null) return;
    const stake = parseFloat(stakeStr);
    if (isNaN(stake) || stake <= 0) {
        alert('Invalid stake amount.');
        return;
    }

    try {
        const result = await apiFetch(`/api/picks/${parlayId}/place`, {
            method: 'POST',
            body: JSON.stringify({
                actual_odds: actualOdds || 225,
                actual_stake: stake,
            }),
        });

        // Update the card visually
        const card = document.getElementById(`parlay-${parlayId}`);
        if (card) {
            card.classList.add('card-placed');
            // Re-render picks to update buttons
            loadPicks();
        }
    } catch (e) {
        alert(`Error placing pick: ${e.message}`);
    }
}

async function skipPick(parlayId) {
    const reason = prompt('Reason for skipping:', 'user_choice');
    if (reason === null) return;

    try {
        await apiFetch(`/api/picks/${parlayId}/skip`, {
            method: 'POST',
            body: JSON.stringify({ reason: reason || 'user_choice' }),
        });

        loadPicks();
    } catch (e) {
        alert(`Error skipping pick: ${e.message}`);
    }
}

// ============================================================================
// Ladder View
// ============================================================================

async function loadLadder() {
    try {
        const [ladder, history] = await Promise.all([
            apiFetch('/api/ladder'),
            apiFetch('/api/ladder/history'),
        ]);

        renderLadderVisual(ladder);
        renderLadderHistory(history);
        renderLadderStats(ladder);

        // Update header
        const info = document.getElementById('header-ladder-info');
        if (ladder.active) {
            info.textContent = `Step ${ladder.step} of ${ladder.total_steps} | $${ladder.bankroll.toFixed(2)}`;
        } else {
            info.textContent = ladder.attempt_id > 0 ? 'Ladder Idle' : 'No ladder started';
        }
    } catch (e) {
        document.getElementById('ladder-visual').innerHTML =
            '<p class="text-gray-500 text-sm">No ladder data available yet.</p>';
        document.getElementById('ladder-history').innerHTML =
            '<p class="text-gray-500 text-sm">No history available.</p>';
    }
}

function renderLadderVisual(ladder) {
    const container = document.getElementById('ladder-visual');
    const totalSteps = ladder.total_steps || 4;
    const currentStep = ladder.step || 0;
    const bankroll = ladder.bankroll || ladder.starting_amount;
    const target = ladder.target_amount;
    const start = ladder.starting_amount;

    // Calculate bankroll at each step (approximate)
    const avgDecimal = 3.25; // +225
    const stepValues = [start];
    for (let i = 1; i <= totalSteps; i++) {
        stepValues.push(Math.round(stepValues[i - 1] * avgDecimal * 100) / 100);
    }

    // Build ladder from top to bottom
    let html = `<div class="text-center mb-4">
        <span class="text-xs text-gray-400 uppercase tracking-wider">Attempt #${ladder.attempt_id || 1}</span>
    </div>`;

    for (let i = totalSteps; i >= 0; i--) {
        const isTarget = i === totalSteps;
        const isStart = i === 0;
        const isCurrent = i === currentStep;
        const isCompleted = i < currentStep;
        const value = isTarget ? target : stepValues[i];

        let nodeClass = 'bg-gray-700 border-2 border-gray-600';
        let label = `Step ${i}`;
        let extra = '';

        if (isTarget) {
            nodeClass = 'bg-gray-700 border-2 border-yellow-500';
            label = 'TARGET';
            extra = '';
        } else if (isStart) {
            label = 'START';
        }

        if (isCompleted) {
            nodeClass = 'bg-green-800 border-2 border-green-500';
        }
        if (isCurrent && ladder.active) {
            nodeClass = 'bg-indigo-800 border-2 border-indigo-400 pulse-active';
            extra = '<span class="text-xs text-indigo-300 ml-2">YOU ARE HERE</span>';
        }

        // Get step result if available
        const stepData = (ladder.steps || []).find(s => s.step === i);
        let resultBadge = '';
        if (stepData && stepData.parlay_result === 'won') {
            resultBadge = `<span class="text-xs text-green-400 ml-2">WON ${formatOdds(stepData.combined_odds)}</span>`;
        } else if (stepData && stepData.parlay_result === 'lost') {
            resultBadge = '<span class="text-xs text-red-400 ml-2">LOST</span>';
        }

        html += `
        <div class="ladder-step flex items-center gap-4 py-3 ${i > 0 ? '' : ''}">
            <div class="text-right w-16 text-xs text-gray-500">$${value >= 1000 ? value.toLocaleString() : value.toFixed ? value.toFixed(0) : value}</div>
            <div class="ladder-node ${nodeClass} flex-shrink-0">
                <span class="text-xs font-bold text-white">${isStart ? 'S' : isTarget ? 'T' : i}</span>
            </div>
            <div class="flex items-center">
                <span class="text-xs text-gray-400">${label}</span>
                ${extra}
                ${resultBadge}
            </div>
        </div>`;
    }

    container.innerHTML = html;
}

function renderLadderHistory(history) {
    const container = document.getElementById('ladder-history');

    if (!history.attempts || history.attempts.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">No ladder attempts yet.</p>';
        return;
    }

    container.innerHTML = history.attempts.map(a => {
        const resultIcon = a.result === 'won' ? '<span class="text-green-400">&#10003;</span>'
            : a.result === 'lost' ? '<span class="text-red-400">&#10007;</span>'
            : '<span class="text-yellow-400">&#9679;</span>';
        const resultText = a.result === 'won' ? 'COMPLETED'
            : a.result === 'lost' ? `LOST at Step ${a.max_step} ($${a.peak_bankroll?.toFixed(2) || '0'})`
            : 'IN PROGRESS';
        const dateStr = a.started_at ? formatDate(a.started_at) : '--';

        return `
        <div class="bg-gray-800 border border-gray-700 rounded-lg p-3">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    ${resultIcon}
                    <span class="text-sm text-white font-medium">Attempt #${a.attempt_id}</span>
                </div>
                <span class="text-xs text-gray-500">${dateStr}</span>
            </div>
            <p class="text-xs text-gray-400 mt-1">${resultText}</p>
        </div>`;
    }).join('');
}

function renderLadderStats(ladder) {
    const container = document.getElementById('ladder-stats');
    const s = ladder.stats || {};

    container.innerHTML = `
        <div class="grid grid-cols-2 gap-4 text-sm">
            <div>
                <p class="text-gray-500 text-xs">Total Attempts</p>
                <p class="text-white font-semibold">${s.total_attempts || 0}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Total Invested</p>
                <p class="text-white font-semibold">$${(s.total_invested || 0).toFixed(2)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Best Step</p>
                <p class="text-white font-semibold">Step ${s.best_step || 0} ($${(s.best_bankroll || 0).toFixed(2)})</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Win Rate</p>
                <p class="text-white font-semibold">${((s.win_rate || 0) * 100).toFixed(1)}%</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Total Returned</p>
                <p class="text-white font-semibold">$${(s.total_returned || 0).toFixed(2)}</p>
            </div>
            <div>
                <p class="text-gray-500 text-xs">Net P/L</p>
                <p class="font-semibold ${(s.total_returned || 0) - (s.total_invested || 0) >= 0 ? 'text-green-400' : 'text-red-400'}">
                    ${formatMoney((s.total_returned || 0) - (s.total_invested || 0))}
                </p>
            </div>
        </div>`;
}

// ============================================================================
// Performance View
// ============================================================================

async function loadPerformance() {
    try {
        const [perf, bets] = await Promise.all([
            apiFetch('/api/performance'),
            apiFetch('/api/bets'),
        ]);

        renderPerformanceCards(perf);
        renderBetHistory(bets.bets || []);

        // Load charts
        loadCharts();
    } catch (e) {
        document.getElementById('perf-shadow').innerHTML =
            '<p class="text-gray-500 text-sm">No performance data yet.</p>';
    }
}

function renderPerformanceCards(perf) {
    const sp = perf.shadow_portfolio || {};
    const lp = perf.ladder_pl || {};
    const clv = perf.clv || {};

    document.getElementById('perf-shadow').innerHTML = `
        <h4 class="text-xs text-gray-400 uppercase tracking-wider mb-3">Shadow Flat-Bet Portfolio</h4>
        <div class="text-2xl font-bold ${sp.total_profit >= 0 ? 'text-green-400' : 'text-red-400'} mb-1">
            ${formatMoney(sp.total_profit || 0)}
        </div>
        <p class="text-sm text-gray-400">
            ${sp.wins || 0}W-${sp.losses || 0}L (${sp.win_rate || 0}%) | ROI: ${sp.roi || 0}%
        </p>
        <div class="mt-2 text-xs text-gray-500">
            ${Object.entries(sp.by_sport || {}).map(([sport, s]) =>
                `${sport.toUpperCase()}: ${s.wins}W-${s.losses}L`
            ).join(' | ') || 'No data'}
        </div>`;

    document.getElementById('perf-ladder-pl').innerHTML = `
        <h4 class="text-xs text-gray-400 uppercase tracking-wider mb-3">Ladder P/L</h4>
        <div class="text-2xl font-bold ${lp.net >= 0 ? 'text-green-400' : 'text-red-400'} mb-1">
            ${formatMoney(lp.net || 0)}
        </div>
        <p class="text-sm text-gray-400">
            Wagered: $${(lp.total_wagered || 0).toFixed(2)} | Returned: $${(lp.total_returned || 0).toFixed(2)}
        </p>`;

    document.getElementById('perf-clv').innerHTML = `
        <h4 class="text-xs text-gray-400 uppercase tracking-wider mb-3">CLV Tracking</h4>
        <div class="text-2xl font-bold ${(clv.average || 0) >= 0 ? 'text-green-400' : 'text-red-400'} mb-1">
            ${clv.average ? (clv.average * 100).toFixed(2) + '%' : '--'}
        </div>
        <p class="text-sm text-gray-400">
            ${clv.count || 0} bets tracked
        </p>
        <div class="mt-2 text-xs text-gray-500">
            Calibration: ${Object.entries(perf.calibration || {}).map(([sport, b]) =>
                `${sport.toUpperCase()} Brier: ${b}`
            ).join(' | ') || 'No data'}
        </div>`;
}

function renderBetHistory(bets) {
    const container = document.getElementById('bet-history-table');

    if (bets.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-sm">No bets recorded yet.</p>';
        return;
    }

    let html = `
    <table class="w-full text-sm">
        <thead>
            <tr class="text-left text-xs text-gray-500 uppercase border-b border-gray-700">
                <th class="pb-2 pr-3">Status</th>
                <th class="pb-2 pr-3">Date</th>
                <th class="pb-2 pr-3">Description</th>
                <th class="pb-2 pr-3">Odds</th>
                <th class="pb-2 pr-3">Result</th>
                <th class="pb-2 text-right">P/L</th>
            </tr>
        </thead>
        <tbody>`;

    for (const b of bets) {
        const statusIcon = b.placed
            ? '<span class="text-green-400" title="Placed">&#10003;</span>'
            : '<span class="text-gray-600" title="Skipped">&#8212;</span>';
        const resultClass = b.result === 'won' ? 'text-green-400'
            : b.result === 'lost' ? 'text-red-400'
            : 'text-gray-400';
        const plDisplay = b.profit_loss !== null ? formatMoney(b.profit_loss) : '--';
        const plClass = (b.profit_loss || 0) >= 0 ? 'text-green-400' : 'text-red-400';

        html += `
        <tr class="bet-row border-b border-gray-800">
            <td class="py-2 pr-3">${statusIcon}</td>
            <td class="py-2 pr-3 text-gray-400">${b.date}</td>
            <td class="py-2 pr-3 text-white">${b.description}</td>
            <td class="py-2 pr-3 font-mono">${formatOdds(b.odds)}</td>
            <td class="py-2 pr-3 ${resultClass} font-medium uppercase">${b.result}</td>
            <td class="py-2 text-right ${b.placed ? plClass : 'text-gray-600'}">${b.placed ? plDisplay : '--'}</td>
        </tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
}

// Filter handlers
function setupFilters() {
    ['filter-sport', 'filter-result', 'filter-placed'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', async () => {
                const sport = document.getElementById('filter-sport').value;
                const result = document.getElementById('filter-result').value;
                const placed = document.getElementById('filter-placed').value;

                let query = '/api/bets?';
                if (sport) query += `sport=${sport}&`;
                if (result) query += `result=${result}&`;
                if (placed) query += `placed=${placed}&`;

                try {
                    const data = await apiFetch(query.slice(0, -1));
                    renderBetHistory(data.bets || []);
                } catch (e) {
                    console.error('Filter error:', e);
                }
            });
        }
    });
}

// ============================================================================
// Charts
// ============================================================================

const chartDefaults = {
    color: '#9ca3af',
    borderColor: '#374151',
};

async function loadCharts() {
    await Promise.all([
        loadPLChart(),
        loadCalibrationChart(),
        loadCLVChart(),
    ]);
}

async function loadPLChart() {
    try {
        const data = await apiFetch('/api/performance/chart/pl_over_time');
        const ctx = document.getElementById('chart-pl');
        if (!ctx) return;

        if (charts.pl) charts.pl.destroy();

        const values = data.datasets?.[0]?.data || [];
        const colors = values.map(v => v >= 0 ? 'rgba(16, 185, 129, 1)' : 'rgba(239, 68, 68, 1)');

        charts.pl = new Chart(ctx, {
            type: 'line',
            data: {
                labels: (data.labels || []).map(l => formatDate(l)),
                datasets: [{
                    label: 'Cumulative P/L ($)',
                    data: values,
                    borderColor: values.length > 0 && values[values.length - 1] >= 0
                        ? 'rgba(16, 185, 129, 1)' : 'rgba(239, 68, 68, 1)',
                    backgroundColor: values.length > 0 && values[values.length - 1] >= 0
                        ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: '#6b7280', maxTicksLimit: 10 }, grid: { color: '#1f2937' } },
                    y: { ticks: { color: '#6b7280', callback: v => `$${v}` }, grid: { color: '#1f2937' } },
                },
            },
        });
    } catch (e) {
        // No data — leave chart empty
    }
}

async function loadCalibrationChart() {
    try {
        const data = await apiFetch('/api/performance/chart/calibration');
        const ctx = document.getElementById('chart-calibration');
        if (!ctx) return;

        if (charts.calibration) charts.calibration.destroy();

        charts.calibration = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [
                    {
                        label: 'Perfect Calibration',
                        data: Array.from({ length: 21 }, (_, i) => ({ x: i * 5, y: i * 5 })),
                        borderColor: 'rgba(107, 114, 128, 0.5)',
                        borderDash: [5, 5],
                        showLine: true,
                        pointRadius: 0,
                    },
                    {
                        label: 'Actual',
                        data: (data.labels || []).map((l, i) => ({
                            x: data.datasets?.[0]?.data?.[i] || 0,
                            y: data.datasets?.[1]?.data?.[i] || 0,
                        })),
                        borderColor: 'rgba(99, 102, 241, 1)',
                        backgroundColor: 'rgba(99, 102, 241, 0.5)',
                        showLine: true,
                        pointRadius: 5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#9ca3af' } } },
                scales: {
                    x: { title: { display: true, text: 'Predicted %', color: '#6b7280' }, ticks: { color: '#6b7280' }, grid: { color: '#1f2937' }, min: 0, max: 100 },
                    y: { title: { display: true, text: 'Actual %', color: '#6b7280' }, ticks: { color: '#6b7280' }, grid: { color: '#1f2937' }, min: 0, max: 100 },
                },
            },
        });
    } catch (e) {
        // No data
    }
}

async function loadCLVChart() {
    try {
        const data = await apiFetch('/api/performance/chart/clv_scatter');
        const ctx = document.getElementById('chart-clv');
        if (!ctx) return;

        if (charts.clv) charts.clv.destroy();

        const values = data.datasets?.[0]?.data || [];
        const pointColors = values.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)');

        charts.clv = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'CLV (%)',
                    data: (data.labels || []).map((l, i) => ({ x: i, y: values[i] || 0 })),
                    backgroundColor: pointColors,
                    pointRadius: 5,
                },
                {
                    label: 'Zero Line',
                    data: [{ x: 0, y: 0 }, { x: Math.max(values.length - 1, 1), y: 0 }],
                    borderColor: 'rgba(107, 114, 128, 0.5)',
                    borderDash: [5, 5],
                    showLine: true,
                    pointRadius: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { title: { display: true, text: 'Bet #', color: '#6b7280' }, ticks: { color: '#6b7280' }, grid: { color: '#1f2937' } },
                    y: { title: { display: true, text: 'CLV %', color: '#6b7280' }, ticks: { color: '#6b7280' }, grid: { color: '#1f2937' } },
                },
            },
        });
    } catch (e) {
        // No data
    }
}

// ============================================================================
// SSE Live Updates
// ============================================================================

function initSSE() {
    if (sseSource) sseSource.close();

    try {
        sseSource = new EventSource(`${API}/events`);

        sseSource.addEventListener('picks_update', () => {
            const activeTab = window.location.hash.replace('#', '') || 'picks';
            if (activeTab === 'picks') loadPicks();
        });

        sseSource.addEventListener('result_update', () => {
            const activeTab = window.location.hash.replace('#', '') || 'picks';
            if (activeTab === 'picks') loadPicks();
            if (activeTab === 'ladder') loadLadder();
            if (activeTab === 'performance') loadPerformance();
        });

        sseSource.addEventListener('ladder_update', () => {
            const activeTab = window.location.hash.replace('#', '') || 'picks';
            if (activeTab === 'ladder') loadLadder();
        });

        sseSource.onerror = () => {
            // Reconnect after a delay
            setTimeout(initSSE, 5000);
        };
    } catch (e) {
        // SSE not supported or failed — silent fallback
    }
}

// ============================================================================
// Init
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    setupFilters();
    initSSE();
});

// ========== Tabs ==========
document.querySelectorAll('.tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

// ========== Helpers ==========
const fmt = n => n == null ? '-' : Number(n).toLocaleString('ko-KR', { maximumFractionDigits: 2 });
const parseList = s => s.split(',').map(x => parseFloat(x.trim())).filter(x => !Number.isNaN(x));

async function api(path, opts = {}) {
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  const r = await fetch(path, opts);
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`${r.status} ${err}`);
  }
  return r.json();
}

// ========== Watchlist ==========
async function loadWatchlist() {
  const list = await api('/api/watchlist');
  const tbody = document.querySelector('#watchlistTable tbody');
  tbody.innerHTML = '';
  const tickerSelects = ['analyzeTicker', 'backtestTicker'].map(id => document.getElementById(id));
  tickerSelects.forEach(s => s.innerHTML = '');

  list.forEach(e => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${e.ticker}</td>
      <td>${e.name}</td>
      <td>${e.industry || '-'}</td>
      <td>${e.memo || '-'}</td>
      <td><button class="secondary" onclick="deleteEntry('${e.ticker}')">삭제</button></td>`;
    tbody.appendChild(tr);

    tickerSelects.forEach(sel => {
      const opt = document.createElement('option');
      opt.value = e.ticker;
      opt.textContent = `${e.ticker} ${e.name}`;
      sel.appendChild(opt);
    });
  });
}

async function deleteEntry(ticker) {
  if (!confirm(`${ticker} 삭제?`)) return;
  await api(`/api/watchlist/${ticker}`, { method: 'DELETE' });
  loadWatchlist();
}

// ========== Search + One-Click Register ==========
let _searchTimer = null;
let _searchActiveIdx = -1;
let _searchResults = [];

const $search = document.getElementById('companySearch');
const $results = document.getElementById('searchResults');
const $status = document.getElementById('fetchStatus');
const $preview = document.getElementById('fetchPreview');

$search.addEventListener('input', () => {
  clearTimeout(_searchTimer);
  const q = $search.value.trim();
  if (!q) { hideResults(); return; }
  _searchTimer = setTimeout(() => doSearch(q), 200);
});

$search.addEventListener('keydown', (e) => {
  const items = $results.querySelectorAll('.item');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _searchActiveIdx = Math.min(_searchActiveIdx + 1, items.length - 1);
    highlightActive(items);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _searchActiveIdx = Math.max(_searchActiveIdx - 1, -1);
    highlightActive(items);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (_searchActiveIdx >= 0 && _searchResults[_searchActiveIdx]) {
      pickCompany(_searchResults[_searchActiveIdx]);
    } else if (_searchResults[0]) {
      pickCompany(_searchResults[0]);
    }
  } else if (e.key === 'Escape') {
    hideResults();
  }
});

document.addEventListener('click', (e) => {
  if (!$results.contains(e.target) && e.target !== $search) hideResults();
});

function highlightActive(items) {
  items.forEach((el, i) => el.classList.toggle('active', i === _searchActiveIdx));
}

function hideResults() {
  $results.classList.remove('visible');
  _searchActiveIdx = -1;
}

async function doSearch(q) {
  try {
    const list = await api(`/api/search-companies?q=${encodeURIComponent(q)}&limit=15`);
    _searchResults = list;
    if (list.length === 0) {
      $results.innerHTML = '<div class="empty">일치하는 회사 없음</div>';
    } else {
      $results.innerHTML = list.map((c, i) => `
        <div class="item" data-idx="${i}">
          <span class="name">${c.name}</span>
          <span class="ticker">${c.ticker}</span>
        </div>`).join('');
      $results.querySelectorAll('.item').forEach(el => {
        el.addEventListener('click', () => pickCompany(_searchResults[+el.dataset.idx]));
      });
    }
    $results.classList.add('visible');
    _searchActiveIdx = -1;
  } catch (e) {
    $results.innerHTML = `<div class="empty" style="color:#dc2626">검색 오류: ${e.message}</div>`;
    $results.classList.add('visible');
  }
}

async function pickCompany(c) {
  hideResults();
  $search.value = `${c.name} (${c.ticker})`;
  $status.style.color = '#6b7280';
  $status.textContent = `⏳ ${c.name} (${c.ticker}) 의 10년치 재무를 DART에서 가져오는 중...`;
  $preview.innerHTML = '';
  try {
    const f = await api(`/api/fetch-fundamentals/${c.ticker}`);
    $status.textContent = `📥 데이터 수신 완료, 저장 중...`;
    await api('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({ fundamentals: f, memo: '' }),
    });
    $status.style.color = '#059669';
    $status.textContent = `✅ ${f.name} 등록 완료 (${f.revenue.length}년치). 분석/백테스트 탭에서 사용하세요.`;
    $preview.innerHTML = renderPreview(f);
    loadWatchlist();
  } catch (e) {
    $status.style.color = '#dc2626';
    $status.textContent = `❌ ${e.message}`;
  }
}

function renderPreview(f) {
  const last5 = (arr, scale = 1e8, suffix = '억') =>
    arr.slice(-5).map(x => `${(x / scale).toLocaleString('ko-KR', { maximumFractionDigits: 0 })}${suffix}`).join(' / ');
  const pct = arr => arr.slice(-5).map(x => `${x.toFixed(1)}%`).join(' / ');
  return `
    <div class="result">
      <h3>${f.name} <span style="color:#6b7280;font-size:14px">${f.ticker}</span></h3>
      <div class="metric-grid">
        <div class="metric"><div class="label">발행주식수</div><div class="value">${fmt(f.shares_outstanding)}</div></div>
        <div class="metric"><div class="label">최근 5년 매출</div><div class="value" style="font-size:14px">${last5(f.revenue)}</div></div>
        <div class="metric"><div class="label">최근 5년 영업이익</div><div class="value" style="font-size:14px">${last5(f.operating_income)}</div></div>
        <div class="metric"><div class="label">최근 5년 ROE</div><div class="value" style="font-size:14px">${pct(f.roe)}</div></div>
        <div class="metric"><div class="label">최근 5년 부채비율</div><div class="value" style="font-size:14px">${pct(f.debt_to_equity)}</div></div>
        <div class="metric"><div class="label">최근 5년 FCF</div><div class="value" style="font-size:14px">${last5(f.fcf)}</div></div>
      </div>
    </div>`;
}

// ========== Analyze ==========
async function runAnalyze() {
  const ticker = document.getElementById('analyzeTicker').value;
  const useGpt = document.getElementById('useGpt').checked;
  if (!ticker) return alert('관찰리스트에 종목을 먼저 등록하세요.');
  const div = document.getElementById('analyzeResult');
  div.innerHTML = '<p>분석 중...</p>';
  try {
    const r = await api(`/api/analyze/${ticker}?use_gpt=${useGpt}`, { method: 'POST' });
    div.innerHTML = renderAnalyze(r);
  } catch (e) {
    div.innerHTML = `<p style="color:#dc2626">실패: ${e.message}</p>`;
  }
}

function renderAnalyze(r) {
  const s = r.signal;
  const checks = Object.entries(s.screen.checks).map(([k, v]) =>
    `<div class="check ${v ? 'pass' : 'fail'}">${v ? '✓' : '✗'} ${k}</div>`).join('');
  const reasons = s.reasons.map(x => `<li>${x}</li>`).join('');
  let gptHtml = '';
  if (r.gpt) {
    const risks = r.gpt.risks.map(x => `<li>${x}</li>`).join('');
    gptHtml = `
      <h3>GPT 정성 평가</h3>
      <div class="metric-grid">
        <div class="metric"><div class="label">해자 점수</div><div class="value">${r.gpt.moat_score}/10</div></div>
        <div class="metric"><div class="label">경영진 점수</div><div class="value">${r.gpt.management_score}/10</div></div>
        <div class="metric"><div class="label">최종 판단</div><div class="value"><span class="tag ${r.gpt.final_verdict}">${r.gpt.final_verdict}</span></div></div>
      </div>
      <p><b>30초 설명:</b> ${r.gpt.thirty_second_pitch}</p>
      <p><b>해자:</b> ${r.gpt.moat_reason}</p>
      <p><b>경영진:</b> ${r.gpt.management_reason}</p>
      <p><b>핵심 위험:</b><ul class="reasons">${risks}</ul></p>
      <p><b>최종 근거:</b> ${r.gpt.final_reason}</p>`;
  } else if (r.gpt_error) {
    gptHtml = `<p style="color:#dc2626">GPT 오류: ${r.gpt_error}</p>`;
  }

  return `
    <div class="metric-grid">
      <div class="metric"><div class="label">정량 시그널</div><div class="value"><span class="tag ${s.action}">${s.action}</span></div></div>
      <div class="metric"><div class="label">현재가</div><div class="value">${fmt(r.current_price)}</div></div>
      <div class="metric"><div class="label">내재가치(주당)</div><div class="value">${fmt(s.intrinsic_per_share)}</div></div>
      <div class="metric"><div class="label">목표 매수가</div><div class="value">${fmt(s.target_buy_price)}</div></div>
      <div class="metric"><div class="label">할인률</div><div class="value ${s.margin_of_safety_pct > 0 ? 'pos' : 'neg'}">${(s.margin_of_safety_pct*100).toFixed(1)}%</div></div>
      <div class="metric"><div class="label">스크리닝</div><div class="value">${(s.screen.score*100).toFixed(0)}점 ${s.screen.passed ? '✓' : '✗'}</div></div>
    </div>
    <h3>체크리스트</h3>
    <div class="checks">${checks}</div>
    <h3>판단 근거</h3>
    <ul class="reasons">${reasons}</ul>
    ${gptHtml}`;
}

// ========== Backtest ==========
let equityChart = null;
async function runBacktest() {
  const ticker = document.getElementById('backtestTicker').value;
  const initial_cash = parseFloat(document.getElementById('btCash').value);
  const days = parseInt(document.getElementById('btDays').value);
  if (!ticker) return alert('관찰리스트에 종목을 먼저 등록하세요.');
  const div = document.getElementById('backtestResult');
  div.innerHTML = '<p>백테스트 중... (KRX 데이터 다운로드)</p>';
  try {
    const r = await api(`/api/backtest/${ticker}`, { method: 'POST', body: JSON.stringify({ initial_cash, days }) });
    div.innerHTML = renderBacktest(r);
    drawEquity(r.equity_curve);
  } catch (e) {
    div.innerHTML = `<p style="color:#dc2626">실패: ${e.message}</p>`;
  }
}

function renderBacktest(r) {
  const s = r.summary;
  const trades = r.trades.map(t => `
    <tr>
      <td>${t.date}</td><td><span class="tag ${t.action}">${t.action}</span></td>
      <td>${fmt(t.price)}</td><td>${fmt(t.qty)}</td><td>${t.reason}</td>
    </tr>`).join('');
  return `
    <div class="metric-grid">
      <div class="metric"><div class="label">초기자본</div><div class="value">${fmt(s.initial_cash)}</div></div>
      <div class="metric"><div class="label">최종자산</div><div class="value">${fmt(s.final_value)}</div></div>
      <div class="metric"><div class="label">총수익률</div><div class="value ${s.total_return_pct >= 0 ? 'pos' : 'neg'}">${s.total_return_pct}%</div></div>
      <div class="metric"><div class="label">CAGR</div><div class="value ${s.cagr_pct >= 0 ? 'pos' : 'neg'}">${s.cagr_pct}%</div></div>
      <div class="metric"><div class="label">최대낙폭(MDD)</div><div class="value neg">${s.max_drawdown_pct}%</div></div>
      <div class="metric"><div class="label">거래 횟수</div><div class="value">${s.num_trades}</div></div>
      <div class="metric"><div class="label">보유일수</div><div class="value">${s.holding_days}</div></div>
      <div class="metric"><div class="label">목표 매수가</div><div class="value">${fmt(s.target_buy_price)}</div></div>
    </div>
    <h3>거래 내역</h3>
    <table><thead><tr><th>일자</th><th>구분</th><th>가격</th><th>수량</th><th>사유</th></tr></thead>
      <tbody>${trades || '<tr><td colspan="5">거래 없음 (가격이 안전마진 미도달)</td></tr>'}</tbody>
    </table>`;
}

function drawEquity(curve) {
  const ctx = document.getElementById('equityChart').getContext('2d');
  if (equityChart) equityChart.destroy();
  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: curve.map(c => c.date),
      datasets: [
        { label: '자산 가치', data: curve.map(c => c.equity), borderColor: '#2563eb', tension: 0.1, yAxisID: 'y' },
        { label: '주가', data: curve.map(c => c.price), borderColor: '#9ca3af', borderDash: [5, 5], tension: 0.1, yAxisID: 'y1' },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: { type: 'linear', position: 'left', title: { display: true, text: '자산' } },
        y1: { type: 'linear', position: 'right', title: { display: true, text: '주가' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

// ========== Init ==========
loadWatchlist();

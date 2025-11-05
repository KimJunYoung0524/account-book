from flask import Flask, request, jsonify, send_file
import os, json, tempfile
import pandas as pd

app = Flask(__name__)

DATA_FILE = 'data.json'


# ------------------ 데이터 로드 & 저장 ------------------
def save_data(data_list):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)


def load_data():
    """data.json을 읽어서 리스트 반환 + id 없는 항목에 id 부여"""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []

        # id가 없는 기존 데이터에 id 자동 부여
        changed = False
        current_max_id = 0
        for item in data:
            try:
                if 'id' in item:
                    current_max_id = max(current_max_id, int(item.get('id', 0)))
            except Exception:
                pass

        next_id = current_max_id + 1
        for item in data:
            if 'id' not in item:
                item['id'] = next_id
                next_id += 1
                changed = True

        if changed:
            save_data(data)

        return data
    except Exception:
        return []


# ------------------ HTML 페이지 ------------------
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>가계부 시스템</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #f5f7fb;
            --card-bg: #ffffff;
            --accent: #4f46e5;
            --accent-light: #eef2ff;
            --border: #e2e8f0;
            --text-main: #111827;
            --text-sub: #6b7280;
            --danger: #ef4444;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0; padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            background-color: var(--bg); color: var(--text-main);
        }
        .wrapper { max-width: 1000px; margin: 24px auto; padding: 0 16px 32px; }
        header {
            display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 16px; gap: 8px;
        }
        header h1 { font-size: 1.4rem; margin: 0; display: flex; align-items: center; gap: 8px; }
        header h1 span.logo-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--accent); display: inline-block; }
        header .subtitle { margin: 0; font-size: 0.85rem; color: var(--text-sub); }

        .header-right {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 6px;
            font-size: 0.8rem;
        }
        .header-user {
            color: var(--text-sub);
        }
        .header-user strong {
            color: var(--text-main);
        }
        .header-buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }

        .card {
            background-color: var(--card-bg); border-radius: 16px; padding: 16px 20px 20px;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06); border: 1px solid var(--border); margin-bottom: 16px;
        }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .card-header h2 { margin: 0; font-size: 1rem; }
        .btn {
            border: none; border-radius: 999px; padding: 8px 14px; font-size: 0.85rem; cursor: pointer;
            display: inline-flex; align-items: center; gap: 6px; background-color: var(--accent); color: #fff;
        }
        .btn.secondary { background-color: var(--accent-light); color: var(--accent); }
        .btn.danger { background-color: var(--danger); color: #fff; }
        .btn:active { transform: translateY(1px); }
        form {
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px 12px; align-items: flex-end;
        }
        .form-group { display: flex; flex-direction: column; gap: 4px; font-size: 0.85rem; }
        label { color: var(--text-sub); }
        input[type="date"], input[type="number"], input[type="text"], select, input[type="month"] {
            border-radius: 10px; border: 1px solid var(--border); padding: 7px 9px; font-size: 0.9rem; width: 100%; outline: none;
        }
        input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-light); }
        .form-actions { text-align: right; }
        .error-message { color: var(--danger); font-size: 0.8rem; margin-top: 4px; }

        .summary-bar {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 6px; font-size: 0.85rem; color: var(--text-sub);
        }
        .summary-bar strong { color: var(--text-main); }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        thead { background-color: #f9fafb; }
        th, td {
            padding: 8px 6px; border-bottom: 1px solid var(--border);
            text-align: left; white-space: nowrap;
        }
        th:last-child, td:last-child { white-space: nowrap; }
        th { font-weight: 600; color: var(--text-sub); }
        tbody tr:hover { background-color: #f3f4ff; }
        .amount-income { color: #16a34a; font-weight: 600; }
        .amount-expense { color: #dc2626; font-weight: 600; }
        .no-data { text-align: center; padding: 14px 0; color: var(--text-sub); }

        .btn-delete-row {
            padding: 4px 10px;
            font-size: 0.75rem;
        }

        @media (max-width: 760px) {
            form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 520px) {
            form { grid-template-columns: 1fr; }
            header { flex-direction: column; align-items: flex-start; }
            .header-right { align-items: flex-start; }
        }

        .filter-row {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            font-size: 0.85rem;
        }
        .filter-row .filter-field {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .filter-row .filter-hint {
            margin: 0;
            color: var(--text-sub);
            font-size: 0.8rem;
        }

        .chart-container {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
        }
        .chart-box {
            flex: 1 1 260px;
        }
        .chart-title {
            font-size: 0.9rem;
            margin-bottom: 6px;
            color: var(--text-sub);
        }
        canvas {
            max-width: 100%;
            max-height: 280px;
        }
        .chart-empty-text {
            font-size: 0.8rem;
            color: var(--text-sub);
            text-align: center;
            margin-top: 4px;
        }

        .month-summary-body {
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-size: 0.85rem;
        }
        .month-summary-numbers {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }
        .month-summary-numbers span strong {
            color: var(--text-main);
        }
        .month-top-expense-list {
            margin: 4px 0 0;
            padding-left: 18px;
            font-size: 0.8rem;
        }
        .month-summary-text {
            margin: 0;
            color: var(--text-sub);
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
<div class="wrapper">
    <header>
        <div>
            <h1><span class="logo-dot"></span> 가계부</h1>
            <p class="subtitle">수입·지출을 간단하게 기록하고 엑셀로 관리하세요.</p>
        </div>
        <div class="header-right">
            <div class="header-user">
                현재 사용자: <strong id="current-user-label">guest</strong>
            </div>
            <div class="header-buttons">
                <button class="btn secondary" id="btn-change-user">사용자 변경</button>
                <button class="btn danger" id="btn-delete-user">사용자 삭제</button>
                <button class="btn secondary" id="btn-download-top">⬇️ 엑셀 다운로드</button>
            </div>
        </div>
    </header>

    <!-- 월별 필터 카드 -->
    <section class="card">
        <div class="card-header">
            <h2>조회 기간</h2>
        </div>
        <div class="filter-row">
            <div class="filter-field">
                <label for="month-filter">월 선택</label>
                <input type="month" id="month-filter">
            </div>
            <div class="filter-field">
                <label>&nbsp;</label>
                <button class="btn secondary" id="btn-clear-filter">전체 보기</button>
            </div>
            <p class="filter-hint">선택한 월 기준으로 목록, 합계, 요약, 그래프가 모두 필터링됩니다. (미선택 시 전체)</p>
        </div>
    </section>

    <!-- 이번 달 요약 카드 -->
    <section class="card">
        <div class="card-header">
            <h2>이번 달 요약</h2>
        </div>
        <div class="month-summary-body">
            <p id="month-summary-label" class="month-summary-text">전체 기간 기준 요약입니다.</p>
            <div class="month-summary-numbers">
                <span>수입: <strong id="month-income">0</strong> 원</span>
                <span>지출: <strong id="month-expense">0</strong> 원</span>
                <span>잔액: <strong id="month-balance">0</strong> 원</span>
            </div>
            <div>
                <p class="month-summary-text">지출 TOP 3 카테고리</p>
                <ul id="month-top-expense-list" class="month-top-expense-list"></ul>
            </div>
        </div>
    </section>

    <!-- 입력 카드 -->
    <section class="card">
        <div class="card-header">
            <h2>내역 입력</h2>
        </div>
        <form id="account-form">
            <div class="form-group">
                <label for="date">날짜</label>
                <input type="date" id="date" required>
            </div>
            <div class="form-group">
                <label for="amount">금액</label>
                <input type="number" id="amount" min="0" placeholder="예: 12000" required>
            </div>
            <div class="form-group">
                <label for="main-category">대분류</label>
                <select id="main-category" required>
                    <option value="">선택하세요</option>
                    <option value="수입">수입</option>
                    <option value="지출">지출</option>
                </select>
            </div>
            <div class="form-group">
                <label for="sub-category">소분류</label>
                <select id="sub-category" required>
                    <option value="">대분류를 먼저 선택하세요</option>
                </select>
            </div>
            <div class="form-group" style="grid-column: span 3;">
                <label for="memo">내용 (메모)</label>
                <input type="text" id="memo" placeholder="예: 점심 식사, 월급, 교통비 등" required>
            </div>
            <div class="form-group form-actions">
                <button type="submit" class="btn">➕ 내역 추가</button>
                <div class="error-message" id="form-error" style="display:none;"></div>
            </div>
        </form>
    </section>

    <!-- 리스트 카드 -->
    <section class="card">
        <div class="card-header">
            <h2>내역 목록</h2>
            <div class="header-buttons">
                <button class="btn secondary" id="btn-clear-entries">내역 전체 삭제</button>
                <button class="btn secondary" id="btn-download-bottom">
                    ⬇️ 엑셀 다운로드
                </button>
            </div>
        </div>

        <div class="summary-bar">
            <div>총 건수: <strong id="summary-count">0</strong> 건</div>
            <div>
                수입 합계: <strong id="summary-income">0</strong> 원 ·
                지출 합계: <strong id="summary-expense">0</strong> 원
            </div>
        </div>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                <tr>
                    <th>날짜</th>
                    <th>대분류</th>
                    <th>소분류</th>
                    <th>금액</th>
                    <th>내용</th>
                    <th>작업</th>
                </tr>
                </thead>
                <tbody id="table-body">
                <tr class="no-data-row">
                    <td colspan="6" class="no-data">아직 저장된 내역이 없습니다.</td>
                </tr>
                </tbody>
            </table>
        </div>
    </section>

    <!-- 그래프 카드 -->
    <section class="card">
        <div class="card-header">
            <h2>그래프 요약</h2>
        </div>
        <div class="chart-container">
            <div class="chart-box">
                <div class="chart-title">대분류 비율 (수입 vs 지출)</div>
                <canvas id="main-pie-chart"></canvas>
                <div id="main-chart-empty" class="chart-empty-text" style="display:none;">
                    수입 또는 지출 내역이 없습니다.
                </div>
            </div>
            <div class="chart-box">
                <div class="chart-title">지출 비율 (소분류 기준)</div>
                <canvas id="expense-pie-chart"></canvas>
                <div id="expense-chart-empty" class="chart-empty-text" style="display:none;">
                    지출 내역이 없습니다. 지출을 입력하면 소분류 기준 원형 그래프가 표시됩니다.
                </div>
            </div>
        </div>
    </section>
</div>

<script>
    const categories = {
        "수입": ["월급", "용돈", "보너스", "이자소득", "기타수입"],
        "지출": ["식비", "교통", "주거", "통신", "쇼핑", "문화생활", "교육", "의료/건강", "기타지출"]
    };

    let currentUser = 'guest';

    const form = document.getElementById('account-form');
    const dateInput = document.getElementById('date');
    const amountInput = document.getElementById('amount');
    const mainSelect = document.getElementById('main-category');
    const subSelect = document.getElementById('sub-category');
    const memoInput = document.getElementById('memo');
    const errorBox = document.getElementById('form-error');

    const tbody = document.getElementById('table-body');
    const summaryCount = document.getElementById('summary-count');
    const summaryIncome = document.getElementById('summary-income');
    const summaryExpense = document.getElementById('summary-expense');

    const btnDownloadTop = document.getElementById('btn-download-top');
    const btnDownloadBottom = document.getElementById('btn-download-bottom');

    const monthFilter = document.getElementById('month-filter');
    const btnClearFilter = document.getElementById('btn-clear-filter');

    const mainChartCanvas = document.getElementById('main-pie-chart');
    const mainChartEmptyText = document.getElementById('main-chart-empty');
    const expenseChartCanvas = document.getElementById('expense-pie-chart');
    const expenseChartEmptyText = document.getElementById('expense-chart-empty');

    const currentUserLabel = document.getElementById('current-user-label');
    const btnChangeUser = document.getElementById('btn-change-user');
    const btnDeleteUser = document.getElementById('btn-delete-user');
    const btnClearEntries = document.getElementById('btn-clear-entries');

    const monthSummaryLabel = document.getElementById('month-summary-label');
    const monthIncomeEl = document.getElementById('month-income');
    const monthExpenseEl = document.getElementById('month-expense');
    const monthBalanceEl = document.getElementById('month-balance');
    const monthTopList = document.getElementById('month-top-expense-list');

    let allItems = [];
    let mainPieChart = null;
    let expensePieChart = null;

    function setToday() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        dateInput.value = `${yyyy}-${mm}-${dd}`;
    }

    function updateSubCategories() {
        const mainValue = mainSelect.value;
        subSelect.innerHTML = "";

        if (!mainValue || !categories[mainValue]) {
            const opt = document.createElement('option');
            opt.value = "";
            opt.textContent = "대분류를 먼저 선택하세요";
            subSelect.appendChild(opt);
            return;
        }

        const defaultOpt = document.createElement('option');
        defaultOpt.value = "";
        defaultOpt.textContent = "소분류 선택";
        subSelect.appendChild(defaultOpt);

        categories[mainValue].forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            subSelect.appendChild(opt);
        });
    }

    function clearError() {
        errorBox.style.display = 'none';
        errorBox.textContent = '';
    }

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.style.display = 'block';
    }

    function formatNumber(num) {
        const n = Number(num) || 0;
        return n.toLocaleString('ko-KR');
    }

    function updateMainPieChart(items) {
        const income = items
            .filter(it => it.main_category === '수입')
            .reduce((sum, it) => sum + (Number(it.amount) || 0), 0);
        const expense = items
            .filter(it => it.main_category === '지출')
            .reduce((sum, it) => sum + (Number(it.amount) || 0), 0);

        if (income === 0 && expense === 0) {
            if (mainPieChart) {
                mainPieChart.destroy();
                mainPieChart = null;
            }
            mainChartCanvas.style.display = 'none';
            mainChartEmptyText.style.display = 'block';
            return;
        }

        mainChartCanvas.style.display = 'block';
        mainChartEmptyText.style.display = 'none';

        if (mainPieChart) {
            mainPieChart.destroy();
        }

        const ctx = mainChartCanvas.getContext('2d');
        mainPieChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: ['수입', '지출'],
                datasets: [{
                    data: [income, expense],
                    backgroundColor: ['#22c55e', '#ef4444']
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                return `${label}: ${value.toLocaleString('ko-KR')}원`;
                            }
                        }
                    }
                }
            }
        });
    }

    function updateExpensePieChart(items) {
        const expenses = items.filter(it => it.main_category === '지출');

        if (!expenses.length) {
            if (expensePieChart) {
                expensePieChart.destroy();
                expensePieChart = null;
            }
            expenseChartCanvas.style.display = 'none';
            expenseChartEmptyText.style.display = 'block';
            return;
        }

        const sums = {};
        expenses.forEach(it => {
            const key = it.sub_category || '기타';
            const amt = Number(it.amount) || 0;
            sums[key] = (sums[key] || 0) + amt;
        });

        const labels = Object.keys(sums);
        const data = labels.map(k => sums[k]);

        expenseChartCanvas.style.display = 'block';
        expenseChartEmptyText.style.display = 'none';

        if (expensePieChart) {
            expensePieChart.destroy();
        }

        const ctx = expenseChartCanvas.getContext('2d');
        expensePieChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: [
                        '#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6',
                        '#0ea5e9', '#6366f1', '#8b5cf6', '#ec4899', '#6b7280'
                    ]
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                return `${label}: ${value.toLocaleString('ko-KR')}원`;
                            }
                        }
                    }
                }
            }
        });
    }

    function updateCharts(items) {
        updateMainPieChart(items);
        updateExpensePieChart(items);
    }

    function updateMonthlySummary(items, monthValue) {
        let income = 0;
        let expense = 0;

        items.forEach(it => {
            const amt = Number(it.amount) || 0;
            if (it.main_category === '수입') income += amt;
            if (it.main_category === '지출') expense += amt;
        });

        monthIncomeEl.textContent = formatNumber(income);
        monthExpenseEl.textContent = formatNumber(expense);
        monthBalanceEl.textContent = formatNumber(income - expense);

        if (monthValue) {
            monthSummaryLabel.textContent = `${monthValue} 기준 요약입니다.`;
        } else {
            monthSummaryLabel.textContent = '전체 기간 기준 요약입니다.';
        }

        monthTopList.innerHTML = '';
        const expenses = items.filter(it => it.main_category === '지출');
        if (!expenses.length) {
            const li = document.createElement('li');
            li.textContent = '지출 내역이 없습니다.';
            monthTopList.appendChild(li);
            return;
        }

        const sums = {};
        expenses.forEach(it => {
            const key = it.sub_category || '기타';
            const amt = Number(it.amount) || 0;
            sums[key] = (sums[key] || 0) + amt;
        });

        const sorted = Object.entries(sums).sort((a, b) => b[1] - a[1]).slice(0, 3);
        sorted.forEach(([name, value]) => {
            const li = document.createElement('li');
            li.textContent = `${name}: ${formatNumber(value)} 원`;
            monthTopList.appendChild(li);
        });
    }

    function renderTable(items) {
        tbody.innerHTML = "";

        if (!items || items.length === 0) {
            const tr = document.createElement('tr');
            tr.classList.add('no-data-row');
            const td = document.createElement('td');
            td.colSpan = 6;
            td.className = 'no-data';
            td.textContent = '아직 저장된 내역이 없습니다.';
            tr.appendChild(td);
            tbody.appendChild(tr);

            summaryCount.textContent = '0';
            summaryIncome.textContent = '0';
            summaryExpense.textContent = '0';

            updateCharts([]);
            return;
        }

        let incomeSum = 0;
        let expenseSum = 0;

        items.sort((a, b) => (a.date || "").localeCompare(b.date || ""));

        items.forEach(item => {
            const tr = document.createElement('tr');

            const tdDate = document.createElement('td');
            tdDate.textContent = item.date || '';
            tr.appendChild(tdDate);

            const tdMain = document.createElement('td');
            tdMain.textContent = item.main_category || '';
            tr.appendChild(tdMain);

            const tdSub = document.createElement('td');
            tdSub.textContent = item.sub_category || '';
            tr.appendChild(tdSub);

            const tdAmount = document.createElement('td');
            const amount = Number(item.amount) || 0;

            if (item.main_category === '수입') {
                incomeSum += amount;
                tdAmount.classList.add('amount-income');
                tdAmount.textContent = '+' + formatNumber(amount);
            } else if (item.main_category === '지출') {
                expenseSum += amount;
                tdAmount.classList.add('amount-expense');
                tdAmount.textContent = '-' + formatNumber(amount);
            } else {
                tdAmount.textContent = formatNumber(amount);
            }
            tr.appendChild(tdAmount);

            const tdMemo = document.createElement('td');
            tdMemo.textContent = item.memo || '';
            tr.appendChild(tdMemo);

            const tdActions = document.createElement('td');
            const btnDel = document.createElement('button');
            btnDel.textContent = '삭제';
            btnDel.className = 'btn secondary btn-delete-row';
            btnDel.dataset.id = item.id;
            tdActions.appendChild(btnDel);
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });

        summaryCount.textContent = String(items.length);
        summaryIncome.textContent = formatNumber(incomeSum);
        summaryExpense.textContent = formatNumber(expenseSum);

        updateCharts(items);
    }

    function applyFilterAndRender() {
        let items = allItems || [];
        const month = monthFilter.value; // YYYY-MM

        if (month) {
            items = items.filter(it => (it.date || '').startsWith(month));
        }

        renderTable(items);
        updateMonthlySummary(items, month);
    }

    async function fetchList() {
        try {
            const res = await fetch('/api/list?user=' + encodeURIComponent(currentUser));
            const data = await res.json();
            if (data.success) {
                allItems = data.items || [];
            } else {
                allItems = [];
            }
        } catch (e) {
            console.error(e);
            allItems = [];
        }
        applyFilterAndRender();
    }

    async function handleSubmit(event) {
        event.preventDefault();
        clearError();

        const date = dateInput.value;
        const amount = amountInput.value;
        const mainCategory = mainSelect.value;
        const subCategory = subSelect.value;
        const memo = memoInput.value.trim();

        if (!date || !amount || !mainCategory || !subCategory || !memo) {
            showError("모든 필드를 입력해 주세요.");
            return;
        }

        if (isNaN(Number(amount))) {
            showError("금액은 숫자로 입력해 주세요.");
            return;
        }

        try {
            const res = await fetch('/api/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json;charset=utf-8'
                },
                body: JSON.stringify({
                    date: date,
                    amount: amount,
                    main_category: mainCategory,
                    sub_category: subCategory,
                    memo: memo,
                    user: currentUser
                })
            });

            const data = await res.json();

            if (!res.ok || !data.success) {
                showError(data.message || "저장 중 오류가 발생했습니다.");
                return;
            }

            setToday();
            amountInput.value = '';
            memoInput.value = '';
            mainSelect.value = '';
            updateSubCategories();
            clearError();

            await fetchList();
        } catch (e) {
            console.error(e);
            showError("서버와 통신 중 오류가 발생했습니다.");
        }
    }

    function downloadExcel() {
        window.location.href = '/api/download?user=' + encodeURIComponent(currentUser);
    }

    async function deleteItem(id) {
        try {
            const res = await fetch('/api/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json;charset=utf-8'
                },
                body: JSON.stringify({
                    id: id,
                    user: currentUser
                })
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                alert(data.message || '삭제 중 오류가 발생했습니다.');
                return;
            }
            await fetchList();
        } catch (e) {
            console.error(e);
            alert('서버와 통신 중 오류가 발생했습니다.');
        }
    }

    async function clearEntriesForUser() {
        if (!confirm(`현재 사용자(${currentUser})의 모든 내역을 삭제할까요?`)) return;
        try {
            const res = await fetch('/api/clear_entries', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json;charset=utf-8'
                },
                body: JSON.stringify({ user: currentUser })
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                alert(data.message || '내역 전체 삭제 중 오류가 발생했습니다.');
                return;
            }
            await fetchList();
        } catch (e) {
            console.error(e);
            alert('서버와 통신 중 오류가 발생했습니다.');
        }
    }

    async function deleteCurrentUser() {
        if (currentUser === 'guest') {
            if (!confirm('guest 사용자의 모든 내역을 삭제하고 초기화할까요?')) return;
        } else {
            if (!confirm(`사용자 "${currentUser}"와 그 사용자의 모든 내역을 삭제합니다. 계속할까요?`)) return;
        }

        try {
            const res = await fetch('/api/delete_user', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json;charset=utf-8'
                },
                body: JSON.stringify({ user: currentUser })
            });
            const data = await res.json();
            if (!res.ok || !data.success) {
                alert(data.message || '사용자 삭제 중 오류가 발생했습니다.');
                return;
            }

            // localStorage에서 사용자 제거 후 guest로 돌아가기
            localStorage.removeItem('accountBookUser');
            currentUser = 'guest';
            currentUserLabel.textContent = currentUser;
            await fetchList();
        } catch (e) {
            console.error(e);
            alert('서버와 통신 중 오류가 발생했습니다.');
        }
    }

    function initUser() {
        const saved = localStorage.getItem('accountBookUser');
        currentUser = saved && saved.trim() ? saved.trim() : 'guest';
        currentUserLabel.textContent = currentUser;
    }

    document.addEventListener('DOMContentLoaded', () => {
        initUser();
        setToday();
        updateSubCategories();
        fetchList();

        mainSelect.addEventListener('change', updateSubCategories);
        form.addEventListener('submit', handleSubmit);

        btnDownloadTop.addEventListener('click', downloadExcel);
        btnDownloadBottom.addEventListener('click', downloadExcel);

        monthFilter.addEventListener('change', applyFilterAndRender);
        btnClearFilter.addEventListener('click', () => {
            monthFilter.value = '';
            applyFilterAndRender();
        });

        btnChangeUser.addEventListener('click', () => {
            const name = prompt('사용자 이름을 입력하세요.', currentUser);
            if (!name) return;
            const trimmed = name.trim();
            if (!trimmed) return;
            currentUser = trimmed;
            localStorage.setItem('accountBookUser', currentUser);
            currentUserLabel.textContent = currentUser;
            fetchList();
        });

        btnDeleteUser.addEventListener('click', deleteCurrentUser);
        btnClearEntries.addEventListener('click', clearEntriesForUser);

        tbody.addEventListener('click', (event) => {
            const target = event.target;
            if (target.classList.contains('btn-delete-row')) {
                const id = Number(target.dataset.id);
                if (!id) return;
                if (!confirm('이 항목을 삭제할까요?')) return;
                deleteItem(id);
            }
        });
    });
</script>
</body>
</html>'''


# ------------------ API ------------------
@app.route('/api/list', methods=['GET'])
def api_list():
    data = load_data()
    user = request.args.get('user')
    if user:
        data = [d for d in data if d.get('user', 'guest') == user]
    return jsonify({"success": True, "items": data})


@app.route('/api/add', methods=['POST'])
def api_add():
    req = request.get_json()
    required = ['date', 'amount', 'memo', 'main_category', 'sub_category']
    if not req or any(f not in req or req[f] == "" for f in required):
        return jsonify({"success": False, "message": "필수 항목이 누락되었습니다."}), 400
    try:
        amount_val = float(req['amount'])
    except ValueError:
        return jsonify({"success": False, "message": "금액은 숫자여야 합니다."}), 400

    data = load_data()
    current_max_id = 0
    for item in data:
        try:
            current_max_id = max(current_max_id, int(item.get('id', 0)))
        except Exception:
            pass
    new_id = current_max_id + 1

    user = req.get('user', 'guest')
    new_item = {
        "id": new_id,
        "user": user,
        "date": req['date'],
        "amount": amount_val,
        "memo": req['memo'],
        "main_category": req['main_category'],
        "sub_category": req['sub_category']
    }
    data.append(new_item)
    save_data(data)
    return jsonify({"success": True, "item": new_item})


@app.route('/api/delete', methods=['POST'])
def api_delete():
    req = request.get_json()
    if not req or 'id' not in req:
        return jsonify({"success": False, "message": "ID가 필요합니다."}), 400

    try:
        target_id = int(req['id'])
    except Exception:
        return jsonify({"success": False, "message": "잘못된 ID입니다."}), 400

    user = req.get('user')

    data = load_data()
    new_data = []
    deleted = False
    for item in data:
        item_id = None
        try:
            item_id = int(item.get('id', 0))
        except Exception:
            item_id = 0

        if (not deleted
            and item_id == target_id
            and (user is None or item.get('user', 'guest') == user)):
            deleted = True
            continue
        new_data.append(item)

    if not deleted:
        return jsonify({"success": False, "message": "항목을 찾을 수 없습니다."}), 404

    save_data(new_data)
    return jsonify({"success": True})


@app.route('/api/clear_entries', methods=['POST'])
def api_clear_entries():
    req = request.get_json()
    if not req or 'user' not in req:
        return jsonify({"success": False, "message": "user가 필요합니다."}), 400

    user = req.get('user')
    data = load_data()
    new_data = [d for d in data if d.get('user', 'guest') != user]

    # 삭제된 게 없어도 그냥 성공 처리
    save_data(new_data)
    return jsonify({"success": True})


@app.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    req = request.get_json()
    if not req or 'user' not in req:
        return jsonify({"success": False, "message": "user가 필요합니다."}), 400

    user = req.get('user')
    data = load_data()
    new_data = [d for d in data if d.get('user', 'guest') != user]

    save_data(new_data)
    return jsonify({"success": True})


@app.route('/api/download', methods=['GET'])
def api_download():
    data = load_data()
    user = request.args.get('user')
    if user:
        data = [d for d in data if d.get('user', 'guest') == user]

    if not data:
        df = pd.DataFrame(columns=["날짜", "금액", "내용", "대분류", "소분류"])
    else:
        df = pd.DataFrame(data).rename(columns={
            "date": "날짜",
            "amount": "금액",
            "memo": "내용",
            "main_category": "대분류",
            "sub_category": "소분류"
        })
        drop_cols = [c for c in ["user", "id"] if c in df.columns]
        if drop_cols:
            df = df.drop(columns=drop_cols)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    df.to_excel(tmp.name, index=False)
    return send_file(tmp.name, as_attachment=True, download_name="가계부.xlsx")


if __name__ == '__main__':
    app.run(debug=True)


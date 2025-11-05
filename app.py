from flask import Flask, request, jsonify, send_file, render_template
import os
import json
import tempfile
import io
import re
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


def get_next_id(data):
    current_max_id = 0
    for item in data:
        try:
            current_max_id = max(current_max_id, int(item.get('id', 0)))
        except Exception:
            pass
    return current_max_id + 1


# ------------------ CSV 헬퍼 함수 (일반 CSV용) ------------------
def _find_col(possible_names, columns):
    for name in possible_names:
        if name in columns:
            return name
    return None


def _normalize_main_category(value, default_main):
    s = str(value).strip()
    if s in ('수입', '입금', 'Income', 'income'):
        return '수입'
    if s in ('지출', '출금', 'Expense', 'expense', '지 급'):
        return '지출'
    return default_main


def _parse_amount(value):
    if value is None:
        return None
    s = str(value)
    s = s.replace(',', '').replace('원', '').strip()
    if s == '' or s == '-':
        return None
    try:
        return float(s)
    except Exception:
        return None


# ------------------ KB국민 ①: 예전 4줄짜리 특수 CSV 파서 ------------------
def parse_kb_kukmin_block(raw_bytes):
    """
    (예전 형식)
    날짜줄 / 금액줄 / 시간줄 / 공백줄 ... 형태의 CSV.
    인식 못 하면 None 반환.
    """
    text = raw_bytes.decode('utf-8', errors='ignore')
    lines = [ln.strip().strip('"') for ln in text.splitlines()]

    date_pattern = re.compile(r'^\s*\d{4}\.\d{2}\.\d{2}')

    def detect_start(lines_):
        for i in range(len(lines_) - 3):
            if date_pattern.match(lines_[i]):
                nums = re.findall(r'[\d,]+', lines_[i + 1])
                if len(nums) >= 2:
                    return i
        return None

    start = detect_start(lines)
    if start is None:
        return None

    records = []
    i = start
    while i + 2 < len(lines):
        date_line = lines[i]
        info_line = lines[i + 1]
        time_line = lines[i + 2]

        m = date_pattern.match(date_line)
        if not m:
            break

        y, mth, d = date_line[m.start():m.end()].split('.')
        date_str = f"{y}-{mth}-{d}"

        nums = [int(n.replace(',', '')) for n in re.findall(r'[\d,]+', info_line)]
        if len(nums) >= 3:
            amt1, amt2, balance = nums[0], nums[1], nums[2]
        elif len(nums) == 2:
            amt1, amt2, balance = nums[0], 0, nums[1]
        else:
            i += 4
            continue

        base_memo = date_line[m.end():].strip()
        prefix = re.split(r'\d', info_line, 1)[0].strip()

        desc_parts = []

        if base_memo:
            desc_parts.append(base_memo)
        if prefix and prefix not in base_memo:
            desc_parts.append(prefix)

        money_desc = []
        if amt1 and amt2:
            money_desc.append(f"금액1 {amt1:,}원")
            money_desc.append(f"금액2 {amt2:,}원")
        elif amt1:
            money_desc.append(f"{amt1:,}원")
        elif amt2:
            money_desc.append(f"{amt2:,}원")

        money_desc.append(f"잔액 {balance:,}원")
        desc_parts.extend(money_desc)

        time_clean = time_line.strip()
        if time_clean:
            desc_parts.append(f"시간 {time_clean}")

        memo = " / ".join(desc_parts) if desc_parts else "KB 거래"

        records.append({
            "date": date_str,
            "amt1": amt1,
            "amt2": amt2,
            "balance": balance,
            "memo": memo,
        })
        i += 4

    if not records:
        return None

    items = []
    prev_bal = None
    for r in records:
        bal = r["balance"]
        if prev_bal is None:
            if r["amt1"] and not r["amt2"]:
                amount = r["amt1"]
                main_category = "지출"
            elif r["amt2"] and not r["amt1"]:
                amount = r["amt2"]
                main_category = "수입"
            else:
                prev_bal = bal
                continue
        else:
            delta = bal - prev_bal
            if delta > 0:
                amount = delta
                main_category = "수입"
            elif delta < 0:
                amount = -delta
                main_category = "지출"
            else:
                prev_bal = bal
                continue

        prev_bal = bal
        sub_category = "기타수입" if main_category == "수입" else "기타지출"
        items.append({
            "date": r["date"],
            "amount": amount,
            "main_category": main_category,
            "sub_category": sub_category,
            "memo": r["memo"]
        })

    if not items:
        return None
    return items


# ------------------ KB국민 ②: 지금 스샷처럼 한 줄짜리 CSV 파서 ------------------
def parse_kb_kukmin_row(raw_bytes):
    """
    (현재 형식)
    예:
    2025.11.05 18:44:18 KB 3,800 0 263,665
    FBS
    2025.11.05 16:39:36 10,000 0 267,465
    ...
    이런 식의 '날짜 시간 + 금액들' 한 줄짜리 형식.
    인식 못 하면 None 반환.
    """
    text = raw_bytes.decode('utf-8', errors='ignore')
    lines = [ln.strip().strip('"') for ln in text.splitlines()]

    dt_pattern = re.compile(r'^\s*(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})')

    items = []
    for idx, line in enumerate(lines):
        m = dt_pattern.match(line)
        if not m:
            continue

        date_raw = m.group(1)  # 2025.11.05
        date_str = date_raw.replace('.', '-')

        tail = line[m.end():].strip()
        nums = [int(n.replace(',', '')) for n in re.findall(r'[\d,]+', tail)]
        if len(nums) < 2:
            continue

        # 보통 [금액, 0, 잔액] 또는 [0, 금액, 잔액]
        amt1 = nums[0]
        amt2 = nums[1]

        if amt1 != 0 and amt2 == 0:
            amount = amt1
            main_category = '지출'
        elif amt2 != 0 and amt1 == 0:
            amount = amt2
            main_category = '수입'
        else:
            # 둘 다 있으면 큰 쪽 기준
            if abs(amt1) >= abs(amt2):
                amount = amt1
                main_category = '지출'
            else:
                amount = amt2
                main_category = '수입'

        # 메모 만들기: 이전 줄 + 현재 줄에서 숫자 앞 텍스트
        prev_line = lines[idx - 1].strip() if idx > 0 else ''
        seg = re.split(r'[\d,]', tail, 1)[0].strip()

        parts = []
        if prev_line and not dt_pattern.match(prev_line) and prev_line not in ('/',):
            parts.append(prev_line)
        if seg:
            parts.append(seg)

        # 중복 제거
        seen = set()
        parts_clean = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                parts_clean.append(p)

        memo = " / ".join(parts_clean) if parts_clean else "KB 거래"

        sub_category = "기타수입" if main_category == "수입" else "기타지출"
        items.append({
            "date": date_str,
            "amount": amount,
            "main_category": main_category,
            "sub_category": sub_category,
            "memo": memo
        })

    if not items:
        return None
    return items


# ------------------ HTML 페이지 ------------------
@app.route('/')
def index():
    return render_template('index.html')


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
        amount_val = float(str(req['amount']).replace(',', '').strip())
    except ValueError:
        return jsonify({"success": False, "message": "금액은 숫자여야 합니다."}), 400

    data = load_data()
    new_id = get_next_id(data)

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


# ------------------ CSV IMPORT (KB 2종 + 일반 CSV) ------------------
@app.route('/api/import', methods=['POST'])
def api_import():
    """
    CSV 파일 업로드 후 여러 건 한 번에 추가하는 엔드포인트.
    1) KB국민은행 한 줄짜리 형식(parse_kb_kukmin_row)
    2) KB국민은행 4줄짜리 옛 형식(parse_kb_kukmin_block)
    3) 그 외 일반 표 형식 CSV (pandas)
    """
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "CSV 파일이 전송되지 않았습니다."}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "CSV 파일을 선택해 주세요."}), 400

    user = request.form.get('user', 'guest')
    default_main = request.form.get('default_main', '지출') or '지출'
    default_sub = request.form.get('default_sub', '기타지출') or '기타지출'

    raw = file.read()

    # 1️⃣ 최신 KB 한 줄짜리 CSV 먼저 시도
    kb_row_items = parse_kb_kukmin_row(raw)
    if kb_row_items is not None:
        data = load_data()
        next_id = get_next_id(data)
        imported_count = 0

        for item in kb_row_items:
            new_item = {
                "id": next_id,
                "user": user,
                "date": item["date"],
                "amount": item["amount"],
                "memo": item["memo"],
                "main_category": item["main_category"],
                "sub_category": item["sub_category"]
            }
            data.append(new_item)
            next_id += 1
            imported_count += 1

        if imported_count == 0:
            return jsonify({
                "success": False,
                "message": "유효한 내역을 찾지 못했습니다. CSV 내용을 확인해 주세요."
            }), 400

        save_data(data)
        return jsonify({"success": True, "imported": imported_count})

    # 2️⃣ 예전 KB 4줄짜리 형식 시도
    kb_block_items = parse_kb_kukmin_block(raw)
    if kb_block_items is not None:
        data = load_data()
        next_id = get_next_id(data)
        imported_count = 0

        for item in kb_block_items:
            new_item = {
                "id": next_id,
                "user": user,
                "date": item["date"],
                "amount": item["amount"],
                "memo": item["memo"],
                "main_category": item["main_category"],
                "sub_category": item["sub_category"]
            }
            data.append(new_item)
            next_id += 1
            imported_count += 1

        if imported_count == 0:
            return jsonify({
                "success": False,
                "message": "유효한 내역을 찾지 못했습니다. CSV 내용을 확인해 주세요."
            }), 400

        save_data(data)
        return jsonify({"success": True, "imported": imported_count})

    # 3️⃣ KB 포맷이 아니면 → 일반 표 형태 CSV 처리 (pandas)
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding='cp949')
        except Exception:
            return jsonify({"success": False, "message": "CSV 파일을 읽을 수 없습니다."}), 400

    if df.empty:
        return jsonify({"success": False, "message": "CSV에 데이터가 없습니다."}), 400

    cols = list(df.columns)

    date_col = _find_col(
        ['날짜', '일자', '거래일자', '거래일', '거래일시', '일시', 'date', 'Date'],
        cols
    )

    amount_col = _find_col(
        ['금액', '거래금액', '금 액', '거래금액(원)', '금액(원)', 'amount', 'Amount'],
        cols
    )

    credit_col = _find_col(
        ['입금', '입금액', '입금(원)', '입금금액', '입금금액(원)'],
        cols
    )
    debit_col = _find_col(
        ['출금', '출금액', '출금(원)', '출금금액', '출금금액(원)'],
        cols
    )

    memo_col = _find_col(['내용', '적요', '메모', '설명', 'memo', 'Memo'], cols)
    main_col = _find_col(['대분류', '구분', '수입지출', '유형', 'type', 'Type'], cols)
    sub_col = _find_col(['소분류', '카테고리', '분류', 'category', 'Category'], cols)

    if not date_col or (not amount_col and not credit_col and not debit_col):
        return jsonify({
            "success": False,
            "message": "CSV에 '날짜' 또는 '일시'와 '금액/입금/출금'에 해당하는 컬럼이 필요합니다."
        }), 400

    data = load_data()
    next_id = get_next_id(data)
    imported_count = 0

    for _, row in df.iterrows():
        date_val = row.get(date_col)
        if pd.isna(date_val):
            continue
        date_str = str(date_val).strip()
        if not date_str:
            continue

        memo_val = ''
        if memo_col:
            mv = row.get(memo_col)
            if not pd.isna(mv):
                memo_val = str(mv).strip()

        main_category = default_main
        amount_val = None

        if amount_col:
            amount_val = _parse_amount(row.get(amount_col))
            if amount_val is None:
                continue

            if main_col:
                main_raw = row.get(main_col)
                main_category = _normalize_main_category(main_raw, default_main)
            else:
                main_category = default_main
        else:
            credit = _parse_amount(row.get(credit_col)) if credit_col else None
            debit = _parse_amount(row.get(debit_col)) if debit_col else None

            credit = credit or 0
            debit = debit or 0

            if credit == 0 and debit == 0:
                continue

            if credit > 0 and debit == 0:
                amount_val = credit
                main_category = '수입'
            elif debit > 0 and credit == 0:
                amount_val = debit
                main_category = '지출'
            else:
                if abs(debit) >= abs(credit):
                    amount_val = debit
                    main_category = '지출'
                else:
                    amount_val = credit
                    main_category = '수입'

        if sub_col:
            sub_raw = row.get(sub_col)
            if pd.isna(sub_raw) or str(sub_raw).strip() == '':
                sub_category = default_sub
            else:
                sub_category = str(sub_raw).strip()
        else:
            sub_category = default_sub

        if amount_val is None:
            continue

        new_item = {
            "id": next_id,
            "user": user,
            "date": date_str,
            "amount": amount_val,
            "memo": memo_val,
            "main_category": main_category,
            "sub_category": sub_category
        }
        data.append(new_item)
        next_id += 1
        imported_count += 1

    if imported_count == 0:
        return jsonify({
            "success": False,
            "message": "유효한 내역을 찾지 못했습니다. CSV 컬럼 구성을 확인해 주세요."
        }), 400

    save_data(data)
    return jsonify({"success": True, "imported": imported_count})


if __name__ == '__main__':
    app.run(debug=True)


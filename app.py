from flask import Flask, request, jsonify, send_file, render_template
import os
import json
import tempfile
import io
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


# ------------------ CSV IMPORT ------------------
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
    s = str(value)
    if s is None:
        return None
    s = s.replace(',', '').replace('원', '').strip()
    if s == '' or s == '-':
        return None
    try:
        return float(s)
    except Exception:
        return None


@app.route('/api/import', methods=['POST'])
def api_import():
    """
    CSV 파일 업로드 후 여러 건 한 번에 추가하는 엔드포인트.
    기대 컬럼(가능한 이름들 예시):
      - 날짜/일자/거래일자/date/Date
      - 금액/거래금액/amount/Amount
      - 내용/적요/메모/설명/memo/Memo
      - (선택) 대분류/구분/수입지출/type/Type
      - (선택) 소분류/카테고리/category/Category
    """
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "CSV 파일이 전송되지 않았습니다."}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "CSV 파일을 선택해 주세요."}), 400

    user = request.form.get('user', 'guest')
    default_main = request.form.get('default_main', '지출') or '지출'
    default_sub = request.form.get('default_sub', '기타지출') or '기타지출'

    # 파일 읽기 (utf-8 → 실패 시 cp949 시도)
    raw = file.read()
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

    date_col = _find_col(['날짜', '일자', '거래일자', 'date', 'Date'], cols)
    amount_col = _find_col(['금액', '거래금액', '금 액', 'amount', 'Amount'], cols)
    memo_col = _find_col(['내용', '적요', '메모', '설명', 'memo', 'Memo'], cols)
    main_col = _find_col(['대분류', '구분', '수입지출', '유형', 'type', 'Type'], cols)
    sub_col = _find_col(['소분류', '카테고리', '분류', 'category', 'Category'], cols)

    if not date_col or not amount_col:
        return jsonify({
            "success": False,
            "message": "CSV에 '날짜'와 '금액'에 해당하는 컬럼이 필요합니다."
        }), 400

    data = load_data()
    next_id = get_next_id(data)

    imported_count = 0
    for _, row in df.iterrows():
        # 날짜
        date_val = row.get(date_col)
        if pd.isna(date_val):
            continue
        date_str = str(date_val).strip()
        if not date_str:
            continue

        # 금액
        amount_val = _parse_amount(row.get(amount_col))
        if amount_val is None:
            continue

        # 메모
        memo_val = ''
        if memo_col:
            mv = row.get(memo_col)
            if not pd.isna(mv):
                memo_val = str(mv).strip()

        # 대분류 / 소분류
        if main_col:
            main_raw = row.get(main_col)
            main_category = _normalize_main_category(main_raw, default_main)
        else:
            main_category = default_main

        if sub_col:
            sub_raw = row.get(sub_col)
            if pd.isna(sub_raw) or str(sub_raw).strip() == '':
                sub_category = default_sub
            else:
                sub_category = str(sub_raw).strip()
        else:
            sub_category = default_sub

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


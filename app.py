from flask import Flask, request, jsonify, send_file, render_template
import os
import json
import tempfile
import io
import re
from datetime import datetime, timezone
import pandas as pd

try:
    import firebase_admin
    from firebase_admin import credentials
    from firebase_admin import firestore as admin_firestore
except Exception:
    firebase_admin = None
    credentials = None
    admin_firestore = None

app = Flask(__name__)

DATA_FILE = 'data.json'
USERS_FILE = 'users.json'


# ------------------ 공용 JSON 로드/저장 ------------------
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


def load_users():
    """users.json 로드 (dict: name -> {password, is_admin})"""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
        users = {}
        for name, info in raw.items():
            if isinstance(info, str):
                users[name] = {"password": info, "is_admin": False}
            elif isinstance(info, dict):
                pwd = info.get("password", "")
                is_admin = bool(info.get("is_admin", False))
                users[name] = {"password": pwd, "is_admin": is_admin}
        return users
    except Exception:
        return {}


def save_users(users: dict):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def ensure_admin_user():
    """
    내부적으로는 '김준영' 이라는 관리자 계정을 유지.
    비밀번호 $Sin10029187, is_admin=True
    (화면에서는 '김준영 + $Sin10029187' 로 관리자로 로그인하게 만들 것)
    """
    users = load_users()
    admin_info = users.get("김준영")
    if not admin_info or admin_info.get("password") != "$Sin10029187" or not admin_info.get("is_admin", False):
        users["김준영"] = {"password": "$Sin10029187", "is_admin": True}
        save_users(users)


ensure_admin_user()


def _init_firestore_client():
    if firebase_admin is None or admin_firestore is None:
        return None
    try:
        if firebase_admin._apps:
            return admin_firestore.client()

        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        service_account_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")

        if service_account_json:
            info = json.loads(service_account_json)
            cred = credentials.Certificate(info)
            firebase_admin.initialize_app(cred)
        elif service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()

        return admin_firestore.client()
    except Exception as e:
        print(f"[WARN] Firestore init failed, fallback to local json: {e}")
        return None


FS_CLIENT = _init_firestore_client()


def _is_firestore_enabled():
    return FS_CLIENT is not None


def _normalize_user_key(user):
    value = str(user or "guest").strip()
    return value or "guest"


def _entries_ref(user):
    user_key = _normalize_user_key(user)
    return FS_CLIENT.collection("accountBooks").document(user_key).collection("entries")


def _parse_date_for_firestore(date_value):
    if date_value is None:
        return datetime.now(timezone.utc)

    text = str(date_value).strip()
    if not text:
        return datetime.now(timezone.utc)

    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return datetime.now(timezone.utc)


def _to_date_string(value):
    if value is None:
        return ""

    try:
        if hasattr(value, "to_datetime"):
            value = value.to_datetime()
    except Exception:
        pass

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d")

    text = str(value).strip()
    if len(text) >= 10:
        return text[:10].replace(".", "-").replace("/", "-")
    return text


def _legacy_to_firestore_payload(user, item):
    main = str(item.get("main_category") or "지출")
    type_value = "income" if main == "수입" else "expense"
    default_category = "기타수입" if type_value == "income" else "기타지출"

    amount_raw = item.get("amount", 0)
    try:
        amount_value = float(str(amount_raw).replace(",", "").strip())
    except Exception:
        amount_value = 0

    return {
        "ownerUid": _normalize_user_key(user),
        "type": type_value,
        "amount": amount_value,
        "category": item.get("sub_category") or default_category,
        "memo": item.get("memo") or "",
        "date": _parse_date_for_firestore(item.get("date")),
        "createdAt": admin_firestore.SERVER_TIMESTAMP,
        "updatedAt": admin_firestore.SERVER_TIMESTAMP,
    }


def _firestore_to_legacy_item(user, doc_id, raw):
    raw = raw or {}
    type_value = str(raw.get("type") or "expense").lower()
    main = "수입" if type_value == "income" else "지출"
    default_sub = "기타수입" if main == "수입" else "기타지출"

    amount_raw = raw.get("amount", 0)
    try:
        amount_value = float(amount_raw)
    except Exception:
        amount_value = 0

    return {
        "id": str(doc_id),
        "user": _normalize_user_key(raw.get("ownerUid") or user),
        "date": _to_date_string(raw.get("date")),
        "amount": amount_value,
        "memo": raw.get("memo") or "",
        "main_category": main,
        "sub_category": raw.get("category") or default_sub,
    }


def _list_items(user):
    user_key = _normalize_user_key(user)
    if _is_firestore_enabled():
        docs = _entries_ref(user_key).stream()
        items = []
        for doc in docs:
            items.append(_firestore_to_legacy_item(user_key, doc.id, doc.to_dict()))
        items.sort(key=lambda x: x.get("date", ""))
        return items

    data = load_data()
    return [d for d in data if d.get("user", "guest") == user_key]


def _add_item(user, item):
    user_key = _normalize_user_key(user)
    if _is_firestore_enabled():
        payload = _legacy_to_firestore_payload(user_key, item)
        ref = _entries_ref(user_key).document()
        ref.set(payload)
        return _firestore_to_legacy_item(user_key, ref.id, payload)

    data = load_data()
    new_id = get_next_id(data)
    new_item = dict(item)
    new_item["id"] = new_id
    new_item["user"] = user_key
    data.append(new_item)
    save_data(data)
    return new_item


def _add_items_bulk(user, items):
    user_key = _normalize_user_key(user)
    if not items:
        return 0

    if _is_firestore_enabled():
        for item in items:
            payload = _legacy_to_firestore_payload(user_key, item)
            _entries_ref(user_key).document().set(payload)
        return len(items)

    data = load_data()
    next_id = get_next_id(data)
    for item in items:
        new_item = dict(item)
        new_item["id"] = next_id
        new_item["user"] = user_key
        data.append(new_item)
        next_id += 1
    save_data(data)
    return len(items)


def _delete_item(user, item_id):
    user_key = _normalize_user_key(user)
    if _is_firestore_enabled():
        target_id = str(item_id).strip()
        if not target_id:
            return False
        doc_ref = _entries_ref(user_key).document(target_id)
        doc = doc_ref.get()
        if not doc.exists:
            return False
        doc_ref.delete()
        return True

    try:
        target_id = int(item_id)
    except Exception:
        return False

    data = load_data()
    new_data = []
    deleted = False
    for item in data:
        try:
            item_int_id = int(item.get("id", 0))
        except Exception:
            item_int_id = 0

        if (not deleted
                and item_int_id == target_id
                and item.get("user", "guest") == user_key):
            deleted = True
            continue
        new_data.append(item)

    if deleted:
        save_data(new_data)
    return deleted


def _clear_items_for_user(user):
    user_key = _normalize_user_key(user)
    if _is_firestore_enabled():
        docs = list(_entries_ref(user_key).stream())
        if not docs:
            return
        for doc in docs:
            doc.reference.delete()
        return

    data = load_data()
    new_data = [d for d in data if d.get("user", "guest") != user_key]
    save_data(new_data)


def _list_all_users_for_admin():
    names = set(load_users().keys())

    if _is_firestore_enabled():
        for doc in FS_CLIENT.collection("accountBooks").stream():
            names.add(doc.id)
    else:
        data = load_data()
        for item in data:
            names.add(item.get("user", "guest"))

    if "김준영" in names:
        names.add("admin")
    return sorted(names)


# ------------------ CSV/금액 파싱 유틸 ------------------
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


def parse_kb_kukmin_block(raw_bytes):
    """
    국민은행 일부 양식(블록 형식) 자동 파싱 시도
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


def parse_kb_kukmin_row(raw_bytes):
    """
    국민은행 '행 단위' 내역 CSV 파싱 시도
    """
    text = raw_bytes.decode('utf-8', errors='ignore')
    lines = [ln.strip().strip('"') for ln in text.splitlines()]

    dt_pattern = re.compile(r'^\s*(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})')

    items = []
    for idx, line in enumerate(lines):
        m = dt_pattern.match(line)
        if not m:
            continue
        date_raw = m.group(1)
        date_str = date_raw.replace('.', '-')
        tail = line[m.end():].strip()

        nums = [int(n.replace(',', '')) for n in re.findall(r'[\d,]+', tail)]
        if len(nums) < 2:
            continue
        amt1, amt2 = nums[0], nums[1]

        if amt1 != 0 and amt2 == 0:
            amount = amt1
            main_category = '지출'
        elif amt2 != 0 and amt1 == 0:
            amount = amt2
            main_category = '수입'
        else:
            if abs(amt1) >= abs(amt2):
                amount = amt1
                main_category = '지출'
            else:
                amount = amt2
                main_category = '수입'

        prev_line = lines[idx - 1].strip() if idx > 0 else ''
        seg = re.split(r'[\d,]', tail, 1)[0].strip()

        parts = []
        if prev_line and not dt_pattern.match(prev_line) and prev_line not in ('/',):
            parts.append(prev_line)
        if seg:
            parts.append(seg)

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


# ------------------ HTML ------------------
@app.route('/')
def index():
    return render_template('index.html')


# ------------------ 사용자 로그인 / 회원 관리 ------------------
@app.route('/api/user_login', methods=['POST'])
def api_user_login():
    """
    - 이름이 '김준영'이고 비밀번호가 '$Sin10029187'면 관리자 로그인으로 처리.
    - 같은 이름이라도 다른 비밀번호로 로그인하면 일반 유저로 로그인 가능.
    """
    req = request.get_json() or {}
    user = (req.get('user') or '').strip()
    password = req.get('password') or ''

    if not user:
        return jsonify({"success": False, "message": "user가 필요합니다."}), 400

    # ✅ '김준영' 전용 처리
    if user == '김준영':
        # 관리자 비밀번호 → 관리자 로그인
        if password == '$Sin10029187':
            return jsonify({"success": True, "is_admin": True, "is_new": False})
        # 그 외 비밀번호 → 일반 유저 로그인
        else:
            return jsonify({"success": True, "is_admin": False, "is_new": False})

    # guest는 비번 없이 (혹은 아무 비번) 그냥 사용 가능하다고 가정
    if user == 'guest':
        return jsonify({"success": True, "is_admin": False, "is_new": False})

    users = load_users()
    info = users.get(user)

    # 등록되지 않은 사용자 → 프론트에서 "새로 만들까요?" 물어보고 /api/user_register 호출
    if not info:
        return jsonify({
            "success": False,
            "need_register": True,
            "message": "등록되지 않은 사용자입니다."
        })

    if info.get("password") != password:
        return jsonify({"success": False, "message": "비밀번호가 올바르지 않습니다."})

    return jsonify({"success": True, "is_admin": bool(info.get("is_admin")), "is_new": False})


@app.route('/api/user_register', methods=['POST'])
def api_user_register():
    """새 일반 사용자 등록 (관리자X). 'guest', 'admin' 이름은 사용 불가"""
    req = request.get_json() or {}
    user = (req.get('user') or '').strip()
    password = req.get('password') or ''

    if not user or not password:
        return jsonify({"success": False, "message": "user와 password가 필요합니다."}), 400

    if user in ('guest', 'admin'):
        return jsonify({"success": False, "message": "해당 이름은 사용할 수 없습니다."}), 400

    users = load_users()
    if user in users:
        return jsonify({"success": False, "message": "이미 존재하는 사용자입니다."}), 400

    users[user] = {"password": password, "is_admin": False}
    save_users(users)
    return jsonify({"success": True})


@app.route('/api/users_for_admin', methods=['GET'])
def api_users_for_admin():
    """관리자 화면에서 조회할 수 있는 사용자 목록"""
    user_list = _list_all_users_for_admin()
    return jsonify({"success": True, "users": user_list})


# ------------------ 가계부 CRUD ------------------
@app.route('/api/list', methods=['GET'])
def api_list():
    user = request.args.get('user', 'guest')
    data = _list_items(user)
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

    user = req.get('user', 'guest')
    item = {
        "date": req['date'],
        "amount": amount_val,
        "memo": req['memo'],
        "main_category": req['main_category'],
        "sub_category": req['sub_category']
    }
    new_item = _add_item(user, item)
    return jsonify({"success": True, "item": new_item})


@app.route('/api/delete', methods=['POST'])
def api_delete():
    req = request.get_json()
    if not req or 'id' not in req:
        return jsonify({"success": False, "message": "ID가 필요합니다."}), 400

    user = req.get('user', 'guest')
    deleted = _delete_item(user, req.get('id'))
    if not deleted:
        return jsonify({"success": False, "message": "항목을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


@app.route('/api/clear_entries', methods=['POST'])
def api_clear_entries():
    req = request.get_json()
    if not req or 'user' not in req:
        return jsonify({"success": False, "message": "user가 필요합니다."}), 400

    user = req.get('user')
    _clear_items_for_user(user)
    return jsonify({"success": True})


@app.route('/api/delete_user', methods=['POST'])
def api_delete_user():
    """
    - 일반 유저 '김준영' (다른 비번으로 로그인) → 삭제 허용
    - 관리자 '김준영' (비번 $Sin10029187 로 로그인한 상태) → 삭제 불가
    """
    req = request.get_json() or {}
    if 'user' not in req:
        return jsonify({"success": False, "message": "user가 필요합니다."}), 400

    user_to_delete = req.get('user')
    login_user = req.get('login_user')         # 현재 로그인한 사용자 이름
    is_admin = bool(req.get('is_admin', False))  # 현재 로그인한 사용자가 관리자 여부

    # ✅ 관리자 김준영 보호:
    # - 삭제 대상이 '김준영' 이고
    # - 로그인한 사용자도 '김준영' 이고
    # - 그 로그인 상태가 관리자일 때만 삭제 불가
    if user_to_delete == '김준영' and login_user == '김준영' and is_admin:
        return jsonify({"success": False, "message": "관리자 계정은 삭제할 수 없습니다."}), 400

    # 그 외에는 모두 삭제 허용 (일반 유저 김준영 포함)
    _clear_items_for_user(user_to_delete)

    users = load_users()
    if user_to_delete in users:
        users.pop(user_to_delete)
        save_users(users)

    return jsonify({"success": True})


@app.route('/api/download', methods=['GET'])
def api_download():
    user = request.args.get('user', 'guest')
    data = _list_items(user)

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


# ------------------ CSV/XLS/XLSX IMPORT ------------------
@app.route('/api/import', methods=['POST'])
def api_import():
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "CSV/엑셀 파일이 전송되지 않았습니다."}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "CSV/엑셀 파일을 선택해 주세요."}), 400

    user = request.form.get('user', 'guest')
    default_main = request.form.get('default_main', '지출') or '지출'
    default_sub = request.form.get('default_sub', '기타지출') or '기타지출'

    ext = os.path.splitext(file.filename)[1].lower()
    raw = file.read()

    # 공통 DF 처리 함수 (CSV/엑셀 공용)
    def handle_dataframe(df):
        if df.empty:
            return jsonify({"success": False, "message": "파일에 데이터가 없습니다."}), 400

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
                "message": "파일에 '날짜' 또는 '일시'와 '금액/입금/출금'에 해당하는 컬럼이 필요합니다."
            }), 400

        items_to_add = []
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

            # ① 단일 금액 컬럼이 있는 경우
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
                # ② 입금/출금 분리된 경우
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
                "date": date_str,
                "amount": amount_val,
                "memo": memo_val,
                "main_category": main_category,
                "sub_category": sub_category
            }
            items_to_add.append(new_item)
            imported_count += 1

        if imported_count == 0:
            return jsonify({
                "success": False,
                "message": "유효한 내역을 찾지 못했습니다. 컬럼 구성을 확인해 주세요."
            }), 400

        _add_items_bulk(user, items_to_add)
        return jsonify({"success": True, "imported": imported_count})

    # ------------------ 1) 엑셀: xlsx ------------------
    if ext == '.xlsx':
        try:
            df = pd.read_excel(io.BytesIO(raw))
        except Exception:
            return jsonify({"success": False, "message": "엑셀(xlsx) 파일을 읽을 수 없습니다."}), 400
        return handle_dataframe(df)

    # ------------------ 2) 엑셀: xls (KB HTML 형식 포함) ------------------
    if ext == '.xls':
        # 1단계: 진짜 엑셀 형식인지 먼저 시도
        try:
            df = pd.read_excel(io.BytesIO(raw))
            return handle_dataframe(df)
        except Exception:
            pass  # 실패하면 HTML 가능성을 보고 다음 단계로

        # 2단계: pandas.read_html() 시도 (환경에 따라 안 될 수 있음)
        tables = None
        try:
            tables = pd.read_html(io.BytesIO(raw))
        except Exception:
            tables = None

        if tables:
            df = tables[-1].copy()
            # 첫 행에 헤더가 들어있는 경우 처리
            if df.shape[0] > 1 and all(isinstance(c, (int, float)) for c in df.columns):
                df.columns = df.iloc[0]
                df = df.iloc[1:]
            df = df.reset_index(drop=True)
            return handle_dataframe(df)

        # 3단계: 의존성 없이 HTML <table> 직접 파싱
        import re as _re
        import html as _html
        try:
            text = raw.decode('utf-8', errors='ignore')
            tables_html = _re.findall(
                r'(<table.*?>.*?</table>)',
                text,
                flags=_re.DOTALL | _re.IGNORECASE
            )
            if not tables_html:
                raise ValueError("no <table> tags found")

            # KB 거래내역 기준: 마지막 테이블이 실제 거래내역
            last_table = tables_html[-1]

            rows = _re.findall(
                r'<tr.*?>(.*?)</tr>',
                last_table,
                flags=_re.DOTALL | _re.IGNORECASE
            )

            table_data = []
            for r in rows:
                cells = _re.findall(
                    r'<t[dh][^>]*>(.*?)</t[dh]>',
                    r,
                    flags=_re.DOTALL | _re.IGNORECASE
                )
                if not cells:
                    continue
                clean_cells = []
                for c in cells:
                    # 태그 제거
                    c2 = _re.sub(r'<.*?>', '', c, flags=_re.DOTALL)
                    c2 = _html.unescape(c2).strip()
                    clean_cells.append(c2)
                if any(clean_cells):
                    table_data.append(clean_cells)

            if len(table_data) <= 1:
                raise ValueError("not enough rows in table")

            header = table_data[0]
            rows_data = table_data[1:]
            width = len(header)

            # 행 길이를 헤더 길이에 맞게 보정
            norm_rows = [
                row + [''] * (width - len(row)) if len(row) < width else row[:width]
                for row in rows_data
            ]

            df = pd.DataFrame(norm_rows, columns=header)
            return handle_dataframe(df)

        except Exception:
            return jsonify({
                "success": False,
                "message": "엑셀(xls) 파일을 읽을 수 없습니다. (HTML 형식 표 구조를 파싱하지 못했습니다.)"
            }), 400

    # ------------------ 3) (기존) CSV: 국민은행 '행 단위' 포맷 시도 ------------------
    kb_row_items = parse_kb_kukmin_row(raw)
    if kb_row_items is not None:
        items_to_add = []
        imported_count = 0
        for item in kb_row_items:
            new_item = {
                "date": item["date"],
                "amount": item["amount"],
                "memo": item["memo"],
                "main_category": item["main_category"],
                "sub_category": item["sub_category"]
            }
            items_to_add.append(new_item)
            imported_count += 1
        if imported_count == 0:
            return jsonify({"success": False, "message": "유효한 내역을 찾지 못했습니다. CSV 내용을 확인해 주세요."}), 400
        _add_items_bulk(user, items_to_add)
        return jsonify({"success": True, "imported": imported_count})

    # ------------------ 4) (기존) CSV: 국민은행 블록 포맷 시도 ------------------
    kb_block_items = parse_kb_kukmin_block(raw)
    if kb_block_items is not None:
        items_to_add = []
        imported_count = 0
        for item in kb_block_items:
            new_item = {
                "date": item["date"],
                "amount": item["amount"],
                "memo": item["memo"],
                "main_category": item["main_category"],
                "sub_category": item["sub_category"]
            }
            items_to_add.append(new_item)
            imported_count += 1
        if imported_count == 0:
            return jsonify({"success": False, "message": "유효한 내역을 찾지 못했습니다. CSV 내용을 확인해 주세요."}), 400
        _add_items_bulk(user, items_to_add)
        return jsonify({"success": True, "imported": imported_count})

    # ------------------ 5) (기존) 일반 CSV ------------------
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding='cp949')
        except Exception:
            return jsonify({"success": False, "message": "CSV 파일을 읽을 수 없습니다."}), 400

    return handle_dataframe(df)


if __name__ == '__main__':
    app.run(debug=True)

from flask import Flask, request, jsonify, send_file, render_template
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
    # templates/index.html 파일을 렌더링
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


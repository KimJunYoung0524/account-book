from flask import Flask, request, jsonify, send_file, render_template
import os, json, tempfile
import pandas as pd

app = Flask(__name__)

DATA_FILE = 'data.json'


# ------------------ 데이터 저장 & 로드 ------------------
def save_data(data_list):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)


def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
        return data
    except Exception:
        return []


# ------------------ 라우트 ------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/add', methods=['POST'])
def api_add():
    req = request.get_json()
    if not req:
        return jsonify(success=False, message="데이터가 비어 있습니다.")
    data = load_data()
    req['id'] = len(data) + 1
    data.append(req)
    save_data(data)
    return jsonify(success=True)


@app.route('/api/list', methods=['GET'])
def api_list():
    data = load_data()
    return jsonify(success=True, items=data)


@app.route('/api/delete', methods=['POST'])
def api_delete():
    req = request.get_json()
    data = load_data()
    data = [d for d in data if d.get('id') != req.get('id')]
    save_data(data)
    return jsonify(success=True)


@app.route('/api/download', methods=['GET'])
def api_download():
    data = load_data()
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
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    df.to_excel(tmp.name, index=False)
    return send_file(tmp.name, as_attachment=True, download_name="가계부.xlsx")


if __name__ == '__main__':
    app.run(debug=True)


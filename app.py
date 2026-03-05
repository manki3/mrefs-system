from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case

import pandas as pd
import re
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import zipfile
import shutil
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
import io




app = Flask(__name__)

# 📂 [수정] 네트워크 공유 폴더 경로 설정 (앞에 r을 꼭 붙여야 합니다!)
UPLOAD_FOLDER = r"\\Desktop-afi1aev\포커스부동산\찍은사진"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# 폴더가 없으면 자동으로 생성
import os
if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    except Exception as e:
        print(f"네트워크 폴더 연결 실패: {e}")

TEMP_FOLDER = "temp_zip"
os.makedirs(TEMP_FOLDER, exist_ok=True)


app.config["SECRET_KEY"] = "super_secret_key_for_login_2025"


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



db = SQLAlchemy(app)
# ✅ 마지막 엑셀 최신화 리포트(누락/파싱 실패 추적용)
LAST_IMPORT_REPORT = None

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.session_protection = "strong"




class Property(db.Model):
    status = db.Column(db.String(20), default='available')
    property_type = db.Column(db.String(50))

    id = db.Column(db.Integer, primary_key=True)

    # ✅ 엑셀(포스) 매물 고유키
    pos_id = db.Column(db.String(50), index=True)
    # ✅ 카톡 TXT 최신 판정용 timestamp
    source_ts = db.Column(db.DateTime)

    building_name = db.Column(db.String(200))

    exclusive_area = db.Column(db.Float)
    contract_area = db.Column(db.Float)

    deposit = db.Column(db.Integer)
    rent = db.Column(db.Integer)

    sale_price = db.Column(db.Integer)

    category = db.Column(db.String(20))
    status = db.Column(db.String(20), default='available')
    
    # ✅ 추가된 비공개 메모 및 옵션 칸
    private_memo = db.Column(db.Text)
    has_interior = db.Column(db.Boolean, default=False)
    has_gonghang = db.Column(db.Boolean, default=False)
    has_corner = db.Column(db.Boolean, default=False)
    


class UploadLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    upload_time = db.Column(db.String(50))
    
class Collection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    memo = db.Column(db.String(200))
    created_at = db.Column(db.String(50))



class CollectionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer)
    property_id = db.Column(db.Integer)
    position = db.Column(db.Integer, default=0)

class PropertyImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, index=True)
    file_path = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()
    
    # ✅ 기존 DB에 private_memo 및 옵션 컬럼들을 안전하게 추가
    try:
        db.session.execute(db.text('ALTER TABLE property ADD COLUMN private_memo TEXT'))
        db.session.commit()
    except:
        pass
    try:
        db.session.execute(db.text('ALTER TABLE property ADD COLUMN has_interior BOOLEAN DEFAULT 0'))
        db.session.execute(db.text('ALTER TABLE property ADD COLUMN has_gonghang BOOLEAN DEFAULT 0'))
        db.session.execute(db.text('ALTER TABLE property ADD COLUMN has_corner BOOLEAN DEFAULT 0'))
        db.session.commit()
    except:
        pass

    # ✅ 기존 DB에 source_ts 컬럼 안전하게 추가
    try:
        db.session.execute(db.text('ALTER TABLE property ADD COLUMN source_ts DATETIME'))
        db.session.commit()
    except:
        pass

    # 🔥 관리자 계정 생성 및 강제 업데이트
    user = User.query.first()
    if not user:
        user = User(username="admin", password=generate_password_hash("5551"))
        db.session.add(user)
    else:
        user.username = "admin"
        user.password = generate_password_hash("5551")
    db.session.commit()



def to_pyung(value):
    try:
        return round(float(value) / 3.3, 2)
    except:
        return 0


def extract_unit(name):
    m = re.search(r"(\d+호)", name)
    if m:
        return m.group(1)
    return ""

def format_sale_price_korean(price):
    try:
        price = int(price)
        if price >= 10000:
            eok = price // 10000
            rest = price % 10000
            if rest == 0: return f"{eok}억"
            # 뒤에 '만'을 붙여서 2억 300만 처럼 나오게 수정
            else: return f"{eok}억 {rest}만"
        else:
            return f"{price}만"
    except:
        return price
    
def safe_int_from_text(text):
    if not text:
        return 0

    text = str(text).strip()

    # 점만 있는 경우 방어
    if text == ".":
        return 0

    match = re.search(r"\d+(?:\.\d+)?", text)
    if match:
        try:
            return int(float(match.group()))
        except:
            return 0

    return 0


def safe_float_from_text(text):
    """문자열에서 안전하게 float 추출 (예: '13.404.' -> 13.404)."""
    if text is None:
        return 0.0
    s = str(text).strip()
    if not s:
        return 0.0
    # 숫자 + (소수점)까지만 추출 (뒤에 붙는 '.' 같은 쓰레기 제거)
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except Exception:
        return 0.0


def building_name_from_private_memo(private_memo: str) -> str:
    """
    비공개메모에서 '...호'까지를 매물카드 건물명으로 사용
    예: '르웨스트웍스 505호 호라는 글자까지가 건물명임 ...' -> '르웨스트웍스 505호'
    """
    if not private_memo:
        return ""

    s = str(private_memo).strip()
    first = s.splitlines()[0].strip() if s.splitlines() else s

    m = re.search(r"^(.+?\d+(?:-\d+)?호)", first)
    if m:
        return " ".join(m.group(1).split()).strip()

    m2 = re.search(r"(.+?\d+(?:-\d+)?호)", s)
    if m2:
        return " ".join(m2.group(1).split()).strip()

    return " ".join(first.split()).strip()


def _guess_options_from_memo(memo_text: str):
    t = re.sub(r"\s+", "", str(memo_text or ""))
    has_interior = bool(re.search(r"(룸|인테리어|탕비실|에어컨|냉난방|스튜디오|강의실|뷰티|미용)", t))
    has_gonghang = bool(re.search(r"(공항대로|공항)", t))
    has_corner = bool(re.search(r"(코너|양창|북동|북서|남동|남서)", t))
    return has_interior, has_gonghang, has_corner


def _parse_price_from_pdf(deal_type: str, price_text: str):
    s = (price_text or "").replace(",", "").replace(" ", "").strip()
    deposit = rent = sale = 0

    if deal_type == "월세":
        if "/" in s:
            left, right = s.split("/", 1)
            deposit = safe_int_from_text(left)
            rent = safe_int_from_text(right)
        else:
            deposit = safe_int_from_text(s)
        return deposit, rent, 0

    if deal_type == "매매":
        sale = safe_int_from_text(s)
        return 0, 0, sale

    return 0, 0, 0


def _cluster_rows_by_y(items, y_tol=16):
    rows = []
    for it in sorted(items, key=lambda z: (z["y"], z["x"])):
        cy = it["y"] + it["h"] / 2
        placed = False
        for r in rows:
            if abs(cy - r["cy"]) <= y_tol:
                r["items"].append(it)
                r["cy"] = (r["cy"] * r["n"] + cy) / (r["n"] + 1)
                r["n"] += 1
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "n": 1, "items": [it]})
    return rows


def _text_in_xrange(row_items, x0, x1):
    parts = []
    for it in sorted(row_items, key=lambda z: z["x"]):
        cx = it["x"] + it["w"] / 2
        if x0 <= cx <= x1:
            parts.append(it["text"])
    s = " ".join(parts).strip()
    return re.sub(r"\s+", " ", s)


def extract_rows_from_pos_pdf(pdf_path: str):
    """
    포스 '매물인쇄' PDF(이미지 기반) → OCR → 표 row 추출
    반환: [{property_type, area_m2, deal_type, price_text, private_memo}]
    """
    if fitz is None or pytesseract is None:
        raise RuntimeError("PyMuPDF(fitz) 또는 pytesseract가 설치되지 않았습니다.")

    doc = fitz.open(pdf_path)
    all_rows = []

    for pi in range(doc.page_count):
        page = doc.load_page(pi)

        # 확대 렌더(정확도↑)
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        data = pytesseract.image_to_data(img, lang="kor+eng", output_type=pytesseract.Output.DICT)

        items = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except:
                conf = -1
            if conf < 40:
                continue
            items.append({
                "text": text,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "conf": conf
            })

        if not items:
            continue

        W, H = img.size
        xr = lambda a: int(W * a)

        # ✅ 포스 표 레이아웃(비율 기반)
        X_PROPERTY_TYPE = (xr(0.09), xr(0.17))
        X_AREA          = (xr(0.52), xr(0.60))
        X_DEAL          = (xr(0.60), xr(0.66))
        X_PRICE         = (xr(0.66), xr(0.74))
        X_MEMO          = (xr(0.74), xr(0.99))

        row_clusters = _cluster_rows_by_y(items, y_tol=16)

        for r in row_clusters:
            row_items = r["items"]
            whole_line = " ".join([x["text"] for x in sorted(row_items, key=lambda z: z["x"])])

            # 헤더/잡음 제거
            if "매물인쇄" in whole_line:
                continue
            if "매물종류" in whole_line and "비공개메모" in whole_line:
                continue
            if "page" in whole_line.lower():
                continue

            property_type = convert_property_type(_text_in_xrange(row_items, *X_PROPERTY_TYPE))
            area_text     = _text_in_xrange(row_items, *X_AREA)
            deal_text     = _text_in_xrange(row_items, *X_DEAL)
            price_text    = _text_in_xrange(row_items, *X_PRICE)
            private_memo  = _text_in_xrange(row_items, *X_MEMO)

            if not private_memo:
                continue

            deal_type = ""
            if "월세" in deal_text:
                deal_type = "월세"
            elif "매매" in deal_text:
                deal_type = "매매"
            else:
                deal_type = "월세" if "/" in (price_text or "") else ""

            area_m2 = safe_float_from_text(area_text)

            all_rows.append({
                "property_type": property_type,
                "area_m2": area_m2,
                "deal_type": deal_type,
                "price_text": price_text,
                "private_memo": private_memo
            })

    return all_rows




def normalize_dong(text):

    # A동
    text = text.replace("제에이동", "A동").replace("에이동", "A동").replace("제A동", "A동").replace("제에이", "A동")
    text = text.replace("제오 에이", "A동").replace("제오에이", "A동")

    # B동
    text = text.replace("제비동", "B동").replace("비동", "B동").replace("제B동", "B동").replace("제비", "B동")

    # 🔥 랜드파크 전용 패치 (오비 = B동)
    if "랜드파크" in text:
        text = text.replace("제오비동", "B동")
        text = text.replace("오비동", "B동")
        text = text.replace("제오비", "B동")
        text = text.replace("오비", "B동")

    # C동
    text = text.replace("제씨동", "C동").replace("씨동", "C동").replace("제C동", "C동").replace("제씨", "C동").replace("제오씨", "C동")

    # 🔥 랜드파크 전용 패치 (오씨 = C동)
    if "랜드파크" in text:
        text = text.replace("오씨동", "C동")
        text = text.replace("오씨", "C동")

    # D동
    text = text.replace("제디동", "D동").replace("디동", "D동").replace("제D동", "D동").replace("제디", "D동")

    return text

def normalize_building_custom(text):
    # 🚀 류마타워 완벽 패치 (기존 유지)
    if "류마타워" in text:
        m = re.search(r"류마타워\s*([12])(?:차)?(?!\d)", text)
        if m:
            text = re.sub(r"류마타워\s*[12](?:차)?\s*", f"류마타워{m.group(1)} ", text, count=1)
        else:
            text = re.sub(r"류마타워\s*", "류마타워1 ", text)

    # 🚨 퀸즈파크 관련 잡다한 '문영' 떼기 (기존 유지)
    text = re.sub(r'문영\s*퀸즈', '퀸즈', text)
    text = re.sub(r'퀸즈파크\s*나인', '퀸즈9', text)
    text = re.sub(r'퀸즈파크\s*9차', '퀸즈9', text)
    text = re.sub(r'퀸즈파크\s*텐', '퀸즈10', text)
    text = re.sub(r'퀸즈파크\s*10차', '퀸즈10', text)
    text = re.sub(r'퀸즈파크\s*11차', '퀸즈11', text)
    text = re.sub(r'퀸즈파크\s*12차', '퀸즈12', text)
    text = re.sub(r'퀸즈파크\s*13차', '퀸즈13', text)
    
    # [수정] 그랑트윈타워 및 주요 명칭 통일 (기존 유지 + 마곡동 제거 강화)
    text = text.replace("두산더랜드파크", "랜드파크")
    text = text.replace("더랜드파크", "랜드파크")
    text = text.replace("마곡동 그랑트윈타워", "그랑트윈타워")
    text = text.replace("마곡그랑트윈타워", "그랑트윈타워")
    # 🔥 마곡동 붙은 모든 그랑트윈 제거 (공백/붙임 모두 대응)
    text = re.sub(r"마곡동\s*그랑트윈타워", "그랑트윈타워", text)
    text = text.replace("마곡동그랑트윈타워", "그랑트윈타워")
    text = text.replace("747타워", "747").replace("747", "747타워")

    # 🔥 소장님 특별 요청 패치 (기존 유지)
    text = text.replace("마곡595", "595타워")
    text = re.sub(r"롯데캐슬\s*르웨스트.*", "르웨스트웍스", text)
    text = text.replace("홈앤쇼핑사옥", "홈앤쇼핑")
    text = text.replace("웰튼메디플렉스", "웰튼병원")

    # 기타 자주 쓰이는 이름들 (소장님의 소중한 리스트 100% 유지)
    text = text.replace("마곡엠밸리9단지 제업무시설동", "엠밸리 9단지")
    text = text.replace("마곡엠밸리9단지 제판매시설2동", "엠밸리 9단지")
    text = text.replace("발산더블유타워", "W타워2")
    text = text.replace("열린엠타워2", "열린M타워")
    text = text.replace("외 1필지 마곡역한일노벨리아타워", "한일노벨리아")
    text = text.replace("외 2필지 가양역더스카이밸리5차 지식산업센터", "스카이밸리")
    text = text.replace("마곡지웰타워", "지웰타워")
    text = text.replace("이너매스마곡2", "이너매스2")
    text = text.replace("놀라움마곡지식산업센터", "놀라움")
    text = text.replace("엠밸리더블유타워3주1", "W타워3")
    text = text.replace("엠밸리더블유타워4", "W타워4")
    text = text.replace("에이스타워마곡", "에이스타워1")
    text = text.replace("마곡사이언스타워2", "사이언스타워2")
    text = text.replace("마곡엠시그니처", "엠시그니처")
    text = text.replace("마곡센트럴타워2", "센트럴타워2")
    text = text.replace("마곡나루역프라이빗타워2", "안강2")
    text = text.replace("외 1필지 아벨테크노", "아벨테크노")
    text = text.replace("마곡테크노타워2", "테크노타워2")
    text = text.replace("리더스퀘어마곡", "리더스퀘어")
    text = text.replace("이너매스마곡1", "이너매스1")
    text = text.replace("우성에스비타워2", "우성SB2")
    text = text.replace("우성에스비타워", "우성SB1") 
    text = text.replace("우성에스비", "우성SB1")   
    text = text.replace("마곡에스비타워3", "우성SB3")
    text = text.replace("한양더챔버 1동", "한양더챔버")
    text = text.replace("마곡센트럴타워1", "센트럴타워1")
    text = text.replace("외 1필지 제원그로브업무", "원그로브")
    text = text.replace("외 1필지 원그로브업무", "원그로브")
    text = text.replace("리더스타워마곡", "리더스타워")
    text = text.replace("마곡나루역보타닉비즈타워", "보타닉비즈타워")
    text = text.replace("마곡나루역 프라이빗타워 1", "안강1")
    text = text.replace("마곡엠밸리7단지", "엠밸리7단지")
    text = text.replace("외 2필지 델타빌딩", "델타빌딩")
    text = text.replace("외 1필지 엔에이치서울축산농협엔에이치서울타워", "NH서울타워")
    text = text.replace("지엠지엘스타", "GMG엘스타")
    text = text.replace("케이스퀘어마곡업무시설", "케이스퀘어")
    text = text.replace("르웨스트시티 제본동", "르웨스트시티")
    text = text.replace("보타닉게이트마곡디38지식산업센터", "보타닉게이트")
    text = text.replace("외 3필지 마곡아이파크디어반", "아이파크디어반")
    text = text.replace("쿠쿠마곡빌딩", "쿠쿠빌딩")
    text = text.replace("마곡보타닉파크프라자를", "보타닉파크프라자")
    text = text.replace("마곡보타닉파크프라자", "보타닉파크프라자")

    # 보타닉파크타워 1/2/3 -> 보타닉파크1/2/3 (TXT/엑셀/DB 매칭 통일)
    text = re.sub(r"마곡보타닉파크타워\s*([123])\s*차?", r"보타닉파크\1", text)
    text = re.sub(r"보타닉파크\s*타워\s*([123])\s*차?", r"보타닉파크\1", text)
    text = re.sub(r"보타닉파크타워\s*([123])\s*차?", r"보타닉파크\1", text)
    text = re.sub(r"보타닉파크\s*([123])\s*차", r"보타닉파크\1", text)

    text = text.replace("엘케이빌딩", "LK빌딩")
    text = text.replace("에스에이치빌딩", "SH빌딩")
    text = text.replace("외 1필지 우림 블루나인 비즈니스센터", "우림블루나인")
    text = text.replace("지상", "")

    # ✅ 리더스애비뉴 표기 통일 (애비뉴/에비뉴 + 마곡)
    text = text.replace("리더스애비뉴마곡", "리더스애비뉴")
    text = text.replace("리더스애비뉴 마곡", "리더스애비뉴")
    text = text.replace("리더스에비뉴", "리더스애비뉴")

    # ✅ 퀸즈파크 숫자 표기 통일 (공백/차 유무)
    text = re.sub(r"퀸즈파크\s*9(?:차)?", "퀸즈9", text)
    text = re.sub(r"퀸즈파크\s*10(?:차)?", "퀸즈10", text)
    text = re.sub(r"퀸즈파크\s*11(?:차)?", "퀸즈11", text)
    text = re.sub(r"퀸즈파크\s*12(?:차)?", "퀸즈12", text)
    text = re.sub(r"퀸즈파크\s*13(?:차)?", "퀸즈13", text)

    return text

def clean_building_name(raw):
    text = str(raw).strip()

    # ✅ '일부/전체' 같은 구분 단어는 살려야 합니다. (층/일부/전체가 사라지면 웰튼병원 분류가 무너짐)
    remove_words = [
        "건축물대장 면적 확인요청", "건축물대장 기준검수요청",
        "면적 확인요청", "면적확인요청", "기준검수요청",
        "건축물대장"
    ]
    for w in remove_words:
        text = text.replace(w, "")

    # 🔥 앞에 붙은 지번(예: 799-1 또는 747 단독) 완벽하게 날리기
    text = re.sub(r"^\d+(?:-\d+)?\s+", "", text)

    # ✅ 층 표기 통일: "제 8층" / "8F" / "8f" → "8층"
    text = re.sub(r"제\s*(\d+)\s*층", r"\1층", text)
    text = re.sub(r"(\d+)\s*[Ff]\b", r"\1층", text)
    text = re.sub(r"(\d+)\s*층", r"\1층", text)

    # ✅ 단, "101호" 같이 '호수'가 명시된 경우에는 층은 중복일 수 있어 제거 (예: "1층 101호")
    if re.search(r"\d+(?:-\d+)?호", text):
        text = re.sub(r"(?:제\s*)?(?:[bB]\s*)?\d+\s*층", "", text)
        text = re.sub(r"(?:[bB]\s*)?\d+\s*[Ff]\b", "", text)

    # 제944호 -> 944호
    text = re.sub(r"제\s*(\d+호)", r"\1", text)

    text = normalize_dong(text)
    text = normalize_building_custom(text)

    # 🔥 퀸즈 9, 10, 11 동(A,B,C) 철벽 방어 및 층수별 상가/사무실 자동 할당 로직
    if "퀸즈" in text:
        text = re.sub(r'[A-Ca-c]동\s*', '', text)
        clean_for_search = re.sub(r'퀸즈\d+', '', text)
        nums = re.findall(r'\d+', clean_for_search)
        if nums:
            unit_str = nums[-1]
            unit_num = int(unit_str)
            floor = unit_num // 100
            last_two = unit_num % 100
            target_dong = ""
            if "퀸즈9" in text:
                if 1 <= last_two <= 10: target_dong = "A동"
                elif 11 <= last_two <= 30: target_dong = "B동"
                elif 31 <= last_two <= 46: target_dong = "C동"
            elif "퀸즈10" in text:
                if floor >= 6:
                    if 1 <= last_two <= 10: target_dong = "A동"
                    elif 11 <= last_two <= 20: target_dong = "B동"
            elif "퀸즈11" in text:

                # 1~4층은 상가 → 동구분 없음
                if 1 <= floor <= 4:
                    target_dong = ""

                # 5층
                elif floor == 5:
                    if (1 <= last_two <= 6) or (23 <= last_two <= 29):
                        target_dong = "A동"
                    elif 7 <= last_two <= 22:
                        target_dong = "B동"

                # 6~11층
                elif 6 <= floor <= 11:
                    if (1 <= last_two <= 8) or (25 <= last_two <= 34):
                        target_dong = "A동"
                    elif 9 <= last_two <= 24:
                        target_dong = "B동"

                # 12층
                elif floor == 12:
                    if (1 <= last_two <= 8) or (19 <= last_two <= 23):
                        target_dong = "A동"
                    elif 9 <= last_two <= 18:
                        target_dong = "B동"
            if target_dong:
                text = re.sub(r'(퀸즈\d+)\s*', rf'\1 {target_dong} ', text)

    # ✅ 하이픈 제거: C동-503호 -> C동 503호로 강제 통일
    text = re.sub(r"([A-Za-z가-힣0-9]+동)\s*-\s*(\d+호?)", r"\1 \2", text)

    # 맨 앞에 쓸데없이 남은 숫자 찌꺼기 제거
    if re.match(r"^\d+\s*(랜드파크|두산더랜드파크|센트럴타워2|에이스타워1|마곡엠밸리9단지|힐스테이트에코마곡역|나인스퀘어|원그로브|엠밸리 9단지|놀라움|델타빌딩|홈앤쇼핑|르웨스트시티|SH빌딩|퀸즈|747타워|웰튼병원)", text):
        text = re.sub(r"^\d+\s*", "", text)

    text = " ".join(text.split())
    return text.strip()

def trim_after_last_ho(line: str) -> str:
    """
    건물명 라인에서 마지막 '호'까지만 남기고 뒤 텍스트 제거
    예:
    "퀸즈10 A동 908호,909호 **아웃**"
    → "퀸즈10 A동 908호,909호"
    """
    if not line:
        return ""

    s = str(line).strip()

    # 811호 / 811-1호 같은 패턴 허용
    matches = list(re.finditer(r"\d+(?:-\d+)?호", s))
    if not matches:
        return s

    last = matches[-1]
    return s[: last.end()].strip()


def split_unit_numbers(text):
    """
    818호
    818호,819호
    818-1호
    정확히 '숫자+호' 패턴만 추출
    """
    return re.findall(r"\d+(?:-\d+)?호", text)



def parse_price_auto(raw):

    if raw is None:
        return "월세", 0, 0, 0

    price = str(raw).strip()
    price = price.replace(",", "").replace(" ", "")

    # -------- 월세 --------
    if "/" in price:
        left, right = price.split("/", 1)

        def parse_money(text):
            if "억" in text:
                parts = text.split("억")
                eok = int(re.findall(r"\d+", parts[0])[0]) * 10000
                rest = int(re.findall(r"\d+", parts[1])[0]) if re.findall(r"\d+", parts[1]) else 0
                return eok + rest
            nums = re.findall(r"\d+", text)
            return int(nums[0]) if nums else 0

        deposit = parse_money(left)
        rent = parse_money(right)

        return "월세", deposit, rent, 0

    # -------- 매매 --------
    numbers = re.findall(r"\d+", price)
    if numbers:
        full_number = "".join(numbers)   # ← 핵심 (전부 이어붙임)
        return "매매", 0, 0, int(full_number)

    return "월세", 0, 0, 0



    


def convert_property_type(raw):

    if not raw:
        return ""

    raw = raw.strip()

    if raw == "상가점포":
        return "상가"

    if raw in ["사무실", "지식산업센터"]:
        return "사무실"

    if raw in ["아파트", "오피스텔"]:
        return "주거용"

    return raw

def extract_info_from_text(text):

    text = text.replace("\r", "")

    lines = text.split("\n")

    building = lines[0].strip() if lines else ""

    exclusive = 0
    contract = 0
    price = ""

    for line in lines:

        line = line.strip()

        # 전용면적 추출
        if "전용" in line:
            match = re.search(r"(\d+\.?\d*)", line)
            if match:
                exclusive = float(match.group(1))

        # 계약면적 추출
        if "계약" in line:
            match = re.search(r"(\d+\.?\d*)", line)
            if match:
                contract = float(match.group(1))

        # 임대/매매가 추출
        if "임대" in line or "매매" in line:
            match = re.search(r"(\d+[,\d]*\s*/\s*\d+[,\d]*|\d+[,\d]*)", line)
            if match:
                price = match.group(1).replace(" ", "")

    return building, exclusive, contract, price



@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))



@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("index"))

    return render_template("login.html")



@app.route("/")
@login_required
def index():
    print("현재 로그인 상태:", current_user.is_authenticated)

    mode = request.args.get("mode", "rent")
    sort = request.args.get("sort", "")
    property_types = [pt for pt in request.args.getlist("property_type") if pt]
    property_type = request.args.get("property_type", "").strip()  # ✅ index.html 오류 방지용

    query = Property.query

    # ✅ 변수 이름(property_types)과 검색 방식(.in_) 수정 완료
    if property_types:
        query = query.filter(Property.property_type.in_(property_types))

    if mode == "sale":
        query = query.filter_by(category="매매")
    else:
        query = query.filter_by(category="월세")

    # 정렬 로직

    # 정렬 로직
    if sort == "rent_asc":
        query = query.order_by(Property.rent.asc(), Property.deposit.asc())
    elif sort == "rent_desc":
        query = query.order_by(Property.rent.desc(), Property.deposit.desc())
    elif sort == "sale_asc":
        query = query.order_by(Property.sale_price.asc())
    elif sort == "sale_desc":
        query = query.order_by(Property.sale_price.desc())
    elif sort == "area_asc":
        query = query.order_by(Property.exclusive_area.asc())
    elif sort == "area_desc":
        query = query.order_by(Property.exclusive_area.desc())
    else:
        if mode == "rent":
            query = query.order_by(Property.rent.asc(), Property.deposit.asc())
        else:
            query = query.order_by(Property.sale_price.asc())

    # --- 여기서부터 페이지 나누기(20개씩) 적용 ---
    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=20, error_out=False)
    properties = pagination.items
    # -------------------------------------

    last_upload = UploadLog.query.order_by(UploadLog.id.desc()).first()
    upload_time = last_upload.upload_time if last_upload else "업로드 기록 없음"

    collections = Collection.query.all()

    existing_pairs = set(
        (item.property_id, item.collection_id)
        for item in CollectionItem.query.all()
    )

    # ✅ 카드 미리보기용 최신 사진 2장 (index/search와 동일)
    thumb_map = {}
    for img in PropertyImage.query.order_by(PropertyImage.id.desc()).all():
        if img.property_id not in thumb_map:
            thumb_map[img.property_id] = []
        if len(thumb_map[img.property_id]) < 2:
            thumb_map[img.property_id].append(img.file_path)

    return render_template(
        "index.html",
        properties=properties,
        mode=mode,
        format_sale_price_korean=format_sale_price_korean,
        upload_time=upload_time,
        property_type=property_type,
        collections=collections,
        existing_pairs=existing_pairs,
        thumb_map=thumb_map,
        pagination=pagination
    )

@app.route("/delete_all")
@login_required
def delete_all():
    # 매물 데이터 전체 삭제
    Property.query.delete()
    db.session.commit()
    # 삭제 후 현재 매물 등록(register) 페이지로 새로고침하며 삭제 알림 표시
    return redirect(url_for("register", deleted=1))


@app.route("/search", methods=["GET"])
@login_required
def search():

    query = Property.query

    building = request.args.get("building", "")
    categories = request.args.getlist("category")
    sort = request.args.get("sort", "")
    property_types = [pt for pt in request.args.getlist("property_type") if pt]  # ✅ 빈값 제거
    opt_interior = request.args.get("opt_interior", "")
    opt_gonghang = request.args.get("opt_gonghang", "")
    opt_corner = request.args.get("opt_corner", "")

    min_deposit = request.args.get("min_deposit", "")
    max_deposit = request.args.get("max_deposit", "")
    min_rent = request.args.get("min_rent", "")
    max_rent = request.args.get("max_rent", "")
    min_area = request.args.get("min_area", "")
    max_area = request.args.get("max_area", "")
    min_sale = request.args.get("min_sale", "")
    max_sale = request.args.get("max_sale", "")

    if building:
        query = query.filter(Property.building_name.like(f"%{building}%"))

    # ✅ 들여쓰기(띄어쓰기) 에러 완벽 해결
    if property_types:
        query = query.filter(Property.property_type.in_(property_types))

    if categories:
        query = query.filter(Property.category.in_(categories))

    if min_deposit:
        query = query.filter(Property.deposit >= int(min_deposit))
    if max_deposit:
        query = query.filter(Property.deposit <= int(max_deposit))

    if min_rent:
        query = query.filter(Property.rent >= int(min_rent))
    if max_rent:
        query = query.filter(Property.rent <= int(max_rent))

    if min_area:
        query = query.filter(Property.exclusive_area >= float(min_area))
    if max_area:
        query = query.filter(Property.exclusive_area <= float(max_area))

    if min_sale:
        query = query.filter(Property.sale_price >= int(min_sale))
    if max_sale:
        query = query.filter(Property.sale_price <= int(max_sale))
    # ✅ 옵션 필터 적용
    if opt_interior == "on":
        query = query.filter(Property.has_interior == True)
    if opt_gonghang == "on":
        query = query.filter(Property.has_gonghang == True)
    if opt_corner == "on":
        query = query.filter(Property.has_corner == True)    

    # 정렬 로직
    if sort == "rent_asc":
        query = query.order_by(
            case((Property.category == "월세", 0), else_=1),
            Property.rent.asc()
        )
    elif sort == "rent_desc":
        query = query.order_by(
            case((Property.category == "월세", 0), else_=1),
            Property.rent.desc()
        )
    elif sort == "sale_asc":
        query = query.order_by(
            case((Property.category == "매매", 0), else_=1),
            Property.sale_price.asc()
        )
    elif sort == "sale_desc":
        query = query.order_by(
            case((Property.category == "매매", 0), else_=1),
            Property.sale_price.desc()
        )
    elif sort == "area_asc":
        query = query.order_by(Property.exclusive_area.asc())
    elif sort == "area_desc":
        query = query.order_by(Property.exclusive_area.desc())

    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=30, error_out=False)
    results = pagination.items

    last_upload = UploadLog.query.order_by(UploadLog.id.desc()).first()
    upload_time = last_upload.upload_time if last_upload else "-"

    collections = Collection.query.all()

    existing_pairs = set(
        (item.property_id, item.collection_id)
        for item in CollectionItem.query.all()
    )

    # ✅ 카드 미리보기용 최신 사진 2장
    thumb_map = {}
    for img in PropertyImage.query.order_by(PropertyImage.id.desc()).all():
        if img.property_id not in thumb_map:
            thumb_map[img.property_id] = []
        if len(thumb_map[img.property_id]) < 2:
            thumb_map[img.property_id].append(img.file_path)

    return render_template(
        "search.html",
        properties=results,
        collections=collections,
        existing_pairs=existing_pairs,
        format_sale_price_korean=format_sale_price_korean,
        upload_time=upload_time,
        thumb_map=thumb_map,
        pagination=pagination  # 🔥 화면에 페이지 버튼을 띄우기 위해 변수 전달! 
    )


def parse_kakao_text(text_data, target_property_type="사무실"):
    lines = text_data.splitlines()
    
    latest_props = {}
    current_title = None
    current_raw_memo = []
    current_status = 'available'
    
    from datetime import datetime, timedelta
    current_date = datetime.now()
    two_months_ago = current_date - timedelta(days=60)
    
    header_pattern = re.compile(r'^\[.+?\] \[(?:오전|오후) \d+:\d+\] (.+)')
    date_pattern = re.compile(r'^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일')

    out_keywords = ['아웃', '매도함', '계약완료', '거래완료', '임대완료', '매매완료', '계약됨', '거래됨', '계약진행중']

    for line in lines:
        line = line.strip()
        if not line or line == "메시지가 삭제되었습니다.":
            continue

        date_match = date_pattern.match(line)
        if date_match:
            current_date = datetime(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
            continue

        if line.startswith("---------------"):
            continue

        match = header_pattern.match(line)
        if match:
            if current_title:
                latest_props[current_title] = {
                    'building_name': current_title,
                    'status': current_status,
                    'raw_memo': current_raw_memo,
                    'date': current_date
                }

            raw_title = match.group(1).strip()
            upper_title = raw_title.upper()
            
            # 띄어쓰기 무시하고 아웃 키워드 검사 (예: "계약 완료" -> "계약완료")
            upper_title_no_space = upper_title.replace(" ", "")

            status = 'available'
            if any(k in upper_title_no_space for k in out_keywords):
                status = 'out'
            elif '보류' in upper_title_no_space:
                status = 'hold'
                
            clean_title = re.sub(r'\*\*.*?\*\*|\*.*?\*|\[.*?\]', '', raw_title).strip()
            clean_title = clean_title.upper()

            current_title = clean_title
            current_status = status
            current_raw_memo = [raw_title.upper()]
            
        elif current_title is not None:
            upper_line = line.upper()
            upper_line_no_space = upper_line.replace(" ", "")
            current_raw_memo.append(upper_line)
            
            if any(k in upper_line_no_space for k in out_keywords):
                current_status = 'out'
            elif '보류' in upper_line_no_space:
                current_status = 'hold'

    if current_title:
        latest_props[current_title] = {
            'building_name': current_title,
            'status': current_status,
            'raw_memo': current_raw_memo,
            'date': current_date
        }

    count = 0
    
    for p in latest_props.values():
        
        # ⚠️ [주의] 오늘 기준 60일(두 달) 이전의 과거 대화는 삭제됨!
        if p['date'] < two_months_ago:
            continue

        if p['status'] == 'out' or p['status'] == 'hold':
            existing = Property.query.filter_by(building_name=p['building_name']).first()
            if existing:
                # 🔥 [자동 청소 로직] 아웃된 매물에 연결된 사진들을 폴더에서 찾아 완전히 삭제합니다.
                orphan_images = PropertyImage.query.filter_by(property_id=existing.id).all()
                for img in orphan_images:
                    try:
                        # 실제 컴퓨터(서버) 폴더에서 이미지 파일 삭제 (용량 확보)
                        path = img.file_path.lstrip("/")
                        if os.path.exists(path):
                            os.remove(path)
                    except:
                        pass
                    # DB에서 사진 기록 삭제
                    db.session.delete(img)
                
                # 매물 데이터 삭제
                db.session.delete(existing)
            continue

        body_text = '\n'.join(p['raw_memo'])
        
        exc_area, con_area = 0.0, 0.0
        # 🔥 [핵심 수정 1] '실평수', '전용면적' 등 다양한 면적 단어 완벽 인식
        exc_match = re.search(r'(?:전용|실평수|실면적|전용면적|실평)\s*[:\s]*(\d+(?:\.\d+)?)', body_text)
        if exc_match: exc_area = float(exc_match.group(1))
            
        con_match = re.search(r'(?:계약|분양면적|분양평수|계약면적|분양)\s*[:\s]*(\d+(?:\.\d+)?)', body_text)
        if con_match: con_area = float(con_match.group(1))

        deposit, rent = 0, 0
        
        body_text_for_rent = re.sub(r'(현|현재|기존)\s*(임대|임차)?\s*(조건|상태|내역|현황).*', '', body_text)
        body_text_for_rent = re.sub(r'현임대\s*[:\s]*[\d,]+.*', '', body_text_for_rent)

        # 🔥 [핵심 수정 2] 슬래시(/) 외에도 '에', '월' 등 다양한 기호로 구분된 월세도 구출!
        rent_match = re.search(r'(?:임대|조건|보증금|월세|금액|가격|보/월|렌트|단기)[^\d\n]*([0-9\.,]+(?:억\s*)?[0-9,]*)\s*(?:만|만원)?\s*(?:/|에|월|월세)\s*(?:월|월세)?\s*([\d,]+)', body_text_for_rent)
        
        if not rent_match:
            rent_match = re.search(r'([0-9\.,]+(?:억\s*)?[0-9,]*)\s*(?:만|만원)?\s*(?:/|에)\s*(?:월|월세)?\s*([\d,]+)', body_text_for_rent)

        if rent_match:
            deposit_raw = rent_match.group(1).replace(',', '').replace(' ', '')
            rent_raw = rent_match.group(2).replace(',', '').replace(' ', '')
            rent = int(float(rent_raw))
            
            if '억' in deposit_raw:
                parts = deposit_raw.split('억')
                if parts[0]:
                    deposit += int(float(parts[0]) * 10000)
                if len(parts) > 1 and parts[1]:
                    clean_p1 = parts[1].replace(',', '').strip()
                    if clean_p1:
                        deposit += int(clean_p1)
            else:
                deposit = int(float(deposit_raw))
        else:
            jeonse_match = re.search(r'전세[^\d\n]*([0-9\.,]+(?:억\s*)?[0-9,]*)', body_text_for_rent)
            if jeonse_match:
                j_raw = jeonse_match.group(1).replace(',', '').replace(' ', '')
                if '억' in j_raw:
                    parts = j_raw.split('억')
                    if parts[0]: deposit += int(float(parts[0]) * 10000)
                    if len(parts) > 1 and parts[1]:
                        clean_p1 = parts[1].strip()
                        if clean_p1: deposit += int(clean_p1)
                else:
                    deposit = int(float(j_raw))

        sale_price = 0
        sale_match_eok = re.search(r'(?:매매|매도|분양|분양가)[^\d\n]*([\d\.,]+)\s*억(?:\s*([\d,]+))?', body_text)
        sale_match_num = re.search(r'(?:매매|매도|분양|분양가)[^\d\n]*([1-9][\d,]{3,})', body_text)
        
        if sale_match_eok:
            eok = float(sale_match_eok.group(1).replace(',', ''))
            sale_price = int(eok * 10000)
            if sale_match_eok.group(2):
                man_str = sale_match_eok.group(2).replace(',', '').strip()
                if man_str:
                    sale_price += int(man_str)
        elif sale_match_num:
            sale_price = int(sale_match_num.group(1).replace(',', ''))

        # 🔥 [가장 중요한 핵심 3] 구명조끼 로직 🔥
        # 가격 파악에 실패해서 0원이 되더라도, '면적(전용,실평수)'이 0이 아니면 버리지 않고 100% 등록함!
        if deposit == 0 and rent == 0 and sale_price == 0 and exc_area == 0.0:
            continue

        has_interior = bool(re.search(r'(룸|인테리어|파티션|가벽|회의실|대표실)', body_text))
        has_corner = bool(re.search(r'(코너|양창)', body_text))
        has_gonghang = bool(re.search(r'(공항)', body_text))

        property_type = target_property_type
            
        category_val = '매매' if (sale_price > 0 and rent == 0) else '월세'

        existing_prop = Property.query.filter_by(building_name=p['building_name']).first()

        if existing_prop:
            existing_prop.exclusive_area = exc_area
            existing_prop.contract_area = con_area
            existing_prop.deposit = deposit
            existing_prop.rent = rent
            existing_prop.sale_price = sale_price
            existing_prop.status = p['status']
            existing_prop.has_interior = has_interior
            existing_prop.has_corner = has_corner
            existing_prop.has_gonghang = has_gonghang
            existing_prop.private_memo = body_text
            existing_prop.category = category_val
            existing_prop.property_type = property_type
            existing_prop.source_ts = datetime.utcnow()
        else:
            new_property = Property(
                building_name=p['building_name'],
                exclusive_area=exc_area,
                contract_area=con_area,
                deposit=deposit,
                rent=rent,
                sale_price=sale_price,
                status=p['status'],
                has_interior=has_interior,
                has_corner=has_corner,
                has_gonghang=has_gonghang,
                private_memo=body_text,
                category=category_val,
                property_type=property_type,
                source_ts=datetime.utcnow()
            )
            db.session.add(new_property)
        
        count += 1
        
    db.session.commit()
    return count


@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        form_type = request.form.get("form_type")
        
        # 🔥 [핵심 2] 업로드 버튼 종류에 따라 함수에 다른 값을 던져줌 🔥
        if form_type in ["kakao_txt_office", "kakao_txt_commercial"]:
            file = request.files.get("file")
            if file and file.filename.endswith('.txt'):
                text_data = file.read().decode('utf-8', errors='ignore')
                
                if form_type == "kakao_txt_office":
                    inserted_count = parse_kakao_text(text_data, "사무실")
                elif form_type == "kakao_txt_commercial":
                    inserted_count = parse_kakao_text(text_data, "상가")
                    
                return redirect(url_for("register", updated="true"))

    rent_count = Property.query.filter_by(category="월세").count()
    sale_count = Property.query.filter_by(category="매매").count()
    
    return render_template("register.html", rent_count=rent_count, sale_count=sale_count)



   


@app.route("/collections")
@login_required
def collections():

    lists = Collection.query.all()

    return render_template(
        "collections.html",
        lists=lists,
    )




@app.route("/collections/new", methods=["POST"])
def new_collection():

    title = request.form.get("title")

    if title:
        c = Collection(
            title=title,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        db.session.add(c)
        db.session.commit()

    return redirect(url_for("collections"))


@app.route("/collections/<int:id>")
@login_required
def collection_detail(id):

    collection = Collection.query.get(id)

    sort = request.args.get("sort", "")

    items = CollectionItem.query.filter_by(collection_id=id).all()

    properties = []

    for item in items:
        p = Property.query.get(item.property_id)
        if p:
            p.collection_item_id = item.id
            properties.append(p)

    # -------- 정렬 로직 --------
    if sort == "name":
        properties = sorted(properties, key=lambda x: x.building_name)

    elif sort == "area_desc":
        properties = sorted(properties, key=lambda x: x.exclusive_area, reverse=True)

    elif sort == "area_asc":
        properties = sorted(properties, key=lambda x: x.exclusive_area)

    elif sort == "rent_desc":
        properties = sorted(properties, key=lambda x: x.rent, reverse=True)

    elif sort == "rent_asc":
        properties = sorted(properties, key=lambda x: x.rent)
    # ---------------------------


        # ✅ 카드 미리보기용 최신 사진 2장 (index/search와 동일)
    # ✅ 카드 미리보기용 최신 사진 2장
    thumb_map = {}
    for img in PropertyImage.query.order_by(PropertyImage.id.desc()).all():
        if img.property_id not in thumb_map:
            thumb_map[img.property_id] = []
        if len(thumb_map[img.property_id]) < 2:
            thumb_map[img.property_id].append(img.file_path)

    return render_template(
        "collection_detail.html",
        collection=collection,
        properties=properties,
        sort=sort,
        thumb_map=thumb_map,
        format_sale_price_korean=format_sale_price_korean
    )


@app.route("/collections/remove/<int:collection_id>/<int:property_id>", methods=["GET", "POST"])
def remove_from_collection(collection_id, property_id):


    CollectionItem.query.filter_by(
        collection_id=collection_id,
        property_id=property_id
    ).delete()

    db.session.commit()

    return redirect(url_for("collection_detail", id=collection_id))


@app.route("/collections/remove_multiple/<int:collection_id>", methods=["POST"])
@login_required
def remove_multiple(collection_id):

    delete_ids = request.form.getlist("delete_ids")

    for property_id in delete_ids:
        CollectionItem.query.filter_by(
            collection_id=collection_id,
            property_id=property_id
        ).delete()

    db.session.commit()

    return redirect(url_for("collection_detail", id=collection_id))

@app.route("/collections/clear/<int:collection_id>")
@login_required
def clear_collection(collection_id):

    CollectionItem.query.filter_by(collection_id=collection_id).delete()

    db.session.commit()

    return redirect(url_for("collection_detail", id=collection_id))



@app.route("/collections/delete/<int:id>")
@login_required
def delete_collection(id):

    CollectionItem.query.filter_by(collection_id=id).delete()
    Collection.query.filter_by(id=id).delete()

    db.session.commit()

    return redirect(url_for("collections"))


@app.route("/collections/reorder", methods=["POST"])
@login_required
def reorder_collection():

    data = request.json

    for item in data:
        db_item = CollectionItem.query.get(item["id"])

        if db_item:
            db_item.position = item["position"]

    db.session.commit()

    return "OK"


@app.route("/add_to_collection", methods=["POST"])
@login_required
def add_to_collection():

    property_id = request.form.get("property_id")
    collection_id = request.form.get("collection_id")

    if not property_id or not collection_id:
        return redirect(request.referrer or url_for("search"))

    exists = CollectionItem.query.filter_by(
        collection_id=collection_id,
        property_id=property_id
    ).first()

    if not exists:
        item = CollectionItem(
            collection_id=collection_id,
            property_id=property_id
        )
        db.session.add(item)
        db.session.commit()

    return "", 204


@app.route("/api/collection/<int:id>/memo", methods=["POST"])
@login_required
def api_save_memo(id):

    collection = Collection.query.get_or_404(id)

    data = request.get_json(silent=True) or {}
    memo = str(data.get("memo","")).strip()[:200]


    collection.memo = memo
    db.session.commit()

    return jsonify({"result": "ok", "memo": memo})


@app.route("/api/collection/<int:id>/memo", methods=["DELETE"])
@login_required
def api_delete_memo(id):

    collection = Collection.query.get_or_404(id)

    collection.memo = ""
    db.session.commit()

    return jsonify({"result": "ok"})

# ✅ 개별 매물 비공개 메모 직접 저장 API 추가
@app.route("/api/property/<int:id>/memo", methods=["POST"])
@login_required
def api_save_property_memo(id):
    p = Property.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    p.private_memo = str(data.get("memo", "")).strip()
    db.session.commit()
    return jsonify({"result": "ok", "memo": p.private_memo})


import re
from datetime import datetime
from werkzeug.utils import secure_filename

@app.route("/upload_images/<int:property_id>", methods=["POST"])
@login_required
def upload_images(property_id):
    files = request.files.getlist("images")
    if not files:
        return jsonify({"result": "fail"}), 400

    p = Property.query.get_or_404(property_id)
    
    def clean(text):
        return re.sub(r'[\\/*?:"<>|]', "_", str(text)).strip()

    full_name = p.building_name.strip() if p.building_name else "미분류"
    base_dir = app.config["UPLOAD_FOLDER"]
    
    matched_dir = None
    remaining_name = full_name

    # --- 1단계: '찍은사진' 폴더와 그 안의 '1. 마곡역', '2. 발산역' 등을 뒤져서 건물명 찾기 ---
    if os.path.exists(base_dir):
        for root, dirs, _ in os.walk(base_dir):
            # '찍은사진'과 그 안의 '1. 마곡역' 등 2단계까지만 탐색 (더 깊이 안 들어감)
            rel_path = os.path.relpath(root, base_dir)
            depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
            if depth > 1:
                dirs[:] = []
                continue
            
            for d in dirs:
                # '파인스퀘어 b동'이 '파인스퀘어' 폴더와 매칭되는지 확인
                if full_name.lower().startswith(d.lower()):
                    # 단어가 정확히 끝나는지 확인 ('파인'이 '파인스퀘어'에 잘못 걸리지 않게)
                    next_idx = len(d)
                    if next_idx == len(full_name) or full_name[next_idx] == ' ':
                        matched_dir = os.path.join(root, d)
                        remaining_name = full_name[next_idx:].strip()
                        break
            if matched_dir:
                break

    # 캡처에 없는 완전 새로운 건물이면 '찍은사진' 최상단에 생성
    if not matched_dir:
        parts = full_name.split()
        b_name = clean(parts[0]) if parts else "미분류"
        matched_dir = os.path.join(base_dir, b_name)
        remaining_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    # --- 2단계: 남은 글자(B동, 915호)를 대소문자 무시하고 매칭하며 폴더 생성 ---
    current_dir = matched_dir
    sub_parts = [clean(part) for part in remaining_name.split() if part]

    for part in sub_parts:
        if os.path.exists(current_dir):
            existing_dirs = [d for d in os.listdir(current_dir) if os.path.isdir(os.path.join(current_dir, d))]
            match_found = False
            for ed in existing_dirs:
                if ed.lower() == part.lower(): # B동 == b동 매칭 성공!
                    current_dir = os.path.join(current_dir, ed)
                    match_found = True
                    break
            if not match_found:
                current_dir = os.path.join(current_dir, part)
        else:
            current_dir = os.path.join(current_dir, part)

    # 최종 계산된 폴더(건물명/동/호수)가 없으면 생성
    os.makedirs(current_dir, exist_ok=True)

    # --- 3단계: 파일 저장 및 DB 연동 ---
    for file in files:
        if file.filename == "": continue
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = f"{timestamp}_{filename}"
        
        # 실제 윈도우 네트워크 폴더에 파일 저장
        save_path = os.path.join(current_dir, save_name)
        file.save(save_path)

        # 사이트에서 사진을 띄우기 위한 가상 경로 변환
        rel_path = os.path.relpath(save_path, app.config["UPLOAD_FOLDER"])
        db_path = "/static/uploads/" + rel_path.replace("\\", "/")
        
        new_img = PropertyImage(property_id=property_id, file_path=db_path)
        db.session.add(new_img)

    db.session.commit()
    return jsonify({"result": "ok"})


@app.route("/bulk_upload_zip", methods=["POST"])
@login_required
def bulk_upload_zip():

    file = request.files.get("zipfile")
    if not file:
        return "no file", 400

    zip_path = os.path.join(TEMP_FOLDER, "upload.zip")
    file.save(zip_path)

    # 압축 풀기
    extract_path = os.path.join(TEMP_FOLDER, "unzipped")
    if os.path.exists(extract_path):
        shutil.rmtree(extract_path)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_path)

    matched = 0
    skipped = 0

    # 건물 폴더 순회
    for building_folder in os.listdir(extract_path):
        building_path = os.path.join(extract_path, building_folder)
        if not os.path.isdir(building_path):
            continue

        # 호수 폴더 순회
        for unit_folder in os.listdir(building_path):
            unit_path = os.path.join(building_path, unit_folder)
            if not os.path.isdir(unit_path):
                continue

            units = split_unit_numbers(unit_folder)

            for unit in units:
                # DB 매칭
                prop = Property.query.filter(
                    Property.building_name.like(f"%{building_folder}%"),
                    Property.building_name.like(f"%{unit}%")
                ).first()

                if not prop:
                    skipped += 1
                    continue

                # 이미지 저장
                for img_name in os.listdir(unit_path):
                    img_path = os.path.join(unit_path, img_name)

                    if not img_name.lower().endswith((".jpg",".jpeg",".png",".webp")):
                        continue

                    new_name = f"{datetime.utcnow().timestamp()}_{img_name}"
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], new_name)

                    shutil.copy(img_path, save_path)

                    db.session.add(PropertyImage(
                        property_id=prop.id,
                        file_path="/" + save_path.replace("\\","/")
                    ))

                    matched += 1

    db.session.commit()

    return f"완료: {matched}개 매칭, {skipped}개 실패"


@app.route("/delete_images/<int:property_id>", methods=["POST"])
@login_required
def delete_images(property_id):

    imgs = PropertyImage.query.filter_by(property_id=property_id).all()

    for img in imgs:
        try:
            path = img.file_path.lstrip("/")
            if os.path.exists(path):
                os.remove(path)
        except:
            pass

        db.session.delete(img)

    db.session.commit()
    return jsonify({"result":"ok"})


@app.route("/delete_images_selected/<int:property_id>", methods=["POST"])
@login_required
def delete_images_selected(property_id):

    data = request.get_json() or {}
    image_ids = data.get("image_ids") or []

    # ids 방어 (문자/빈값 들어와도 터지지 않게)
    try:
        image_ids = [int(x) for x in image_ids]
    except:
        return jsonify({"result":"bad_ids"}), 400

    if not image_ids:
        return jsonify({"result":"no_ids"}), 400

    imgs = PropertyImage.query.filter(
        PropertyImage.property_id == property_id,
        PropertyImage.id.in_(image_ids)
    ).all()

    for img in imgs:
        try:
            path = img.file_path.lstrip("/")
            if os.path.exists(path):
                os.remove(path)
        except:
            pass

        db.session.delete(img)

    db.session.commit()
    return jsonify({"result":"ok"})

@app.route("/preview")
def preview():
    return render_template("preview.html")



@app.route("/property/<int:id>")
@login_required
def property_detail(id):
    from_collection_id = request.args.get("from_collection_id", type=int)

    p = Property.query.get_or_404(id)

    images = PropertyImage.query.filter_by(property_id=id).order_by(PropertyImage.id.desc()).all()

    # ✅ 상세페이지에서도 리스트 담기 가능하도록 데이터 전달
    collections = Collection.query.all()

    existing_pairs = set(
        (item.property_id, item.collection_id)
        for item in CollectionItem.query.filter_by(property_id=id).all()
    )

    return render_template(
        "property_detail.html",
        p=p,
        images=images,
        collections=collections,
        existing_pairs=existing_pairs,
        from_collection_id=from_collection_id,
        format_sale_price_korean=format_sale_price_korean
    )


@app.route("/delete_all_memos", methods=["POST"])
@login_required
def delete_all_memos():
    # 비공개 메모와, 메모 인식으로 자동 체크된 옵션들까지 모두 초기화
    db.session.query(Property).update({
        Property.private_memo: None,
        Property.has_interior: False,
        Property.has_gonghang: False,
        Property.has_corner: False
    })
    db.session.commit()
    
    # 작업 완료 후, 버튼을 눌렀던 이전 페이지로 새로고침
    return redirect(request.referrer or url_for('register'))



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


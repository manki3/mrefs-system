from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case

import pandas as pd
import re
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import zipfile
import shutil
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

TEMP_FOLDER = "temp_zip"
os.makedirs(TEMP_FOLDER, exist_ok=True)


app.config["SECRET_KEY"] = "super_secret_key_for_login_2025"


app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.session_protection = "strong"




class Property(db.Model):
    status = db.Column(db.String(20), default='available')
    property_type = db.Column(db.String(50))


    id = db.Column(db.Integer, primary_key=True)

    building_name = db.Column(db.String(200))

    exclusive_area = db.Column(db.Float)
    contract_area = db.Column(db.Float)

    deposit = db.Column(db.Integer)
    rent = db.Column(db.Integer)

    sale_price = db.Column(db.Integer)

    category = db.Column(db.String(20))

    status = db.Column(db.String(20), default='available')


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

    if not User.query.first():
        admin = User(
            username="admin",
            password=generate_password_hash("1234")
        )
        db.session.add(admin)
        db.session.commit()



def to_pyung(value):
    try:
        return round(float(value) / 3.3, 2)
    except:
        return 0


def format_sale_price_korean(price):

    try:
        price = int(price)

        if price >= 10000:
            eok = price // 10000
            rest = price % 10000

            if rest == 0:
                return f"{eok}억"
            else:
                return f"{eok}억{rest}"
        else:
            return f"{price}"
    except:
        return price


def normalize_dong(text):

    text = text.replace("제에이동", "A동")
    text = text.replace("에이동", "A동")
    text = text.replace("제A동", "A동")
    text = text.replace("제에이", "A동")

    text = text.replace("제오 에이", "A동")

    text = text.replace("제비동", "B동")
    text = text.replace("비동", "B동")
    text = text.replace("제비", "B동")

    text = text.replace("제씨동", "C동")
    text = text.replace("씨동", "C동")
    text = text.replace("제오씨", "C동")
    text = text.replace("제오에이", "A동")

    return text


def normalize_building_custom(text):

    text = text.replace("마곡엠밸리9단지 제업무시설동", "엠밸리 9단지")
    text = text.replace("마곡그랑트윈타워 B동", "그랑트윈타워 B동")
    text = text.replace("발산더블유타워", "W타워2")
    text = text.replace("열린엠타워2", "열린M타워")
    text = text.replace("외 1필지 마곡역한일노벨리아타워", "한일노벨리아")
    text = text.replace("외 2필지 가양역더스카이밸리5차 지식산업센터", "스카이밸리")
    text = text.replace("마곡지웰타워", "지웰타워")
    text = text.replace("이너매스마곡2", "이너매스2")
    text = text.replace("놀라움마곡지식산업센터", "놀라움")
    text = text.replace("마곡그랑트윈타워 A동", "그랑트윈타워 A동")
    text = text.replace("엠밸리더블유타워3주1", "W타워3")
    text = text.replace("엠밸리더블유타워4", "W타워4")
    text = text.replace("에이스타워마곡", "에이스타워1")
    text = text.replace("마곡사이언스타워2", "사이언스타워2")
    text = text.replace("마곡엠시그니처", "엠시그니처")
    text = text.replace("마곡센트럴타워2", "센트럴타워2")
    text = text.replace("문영퀸즈파크11차", "퀸즈11")
    text = text.replace("마곡나루역프라이빗타워2", "안강2")
    text = text.replace("외 1필지 아벨테크노", "아벨테크노")
    text = text.replace("마곡테크노타워2", "테크노타워2")
    text = text.replace("퀸즈파크나인", "퀸즈9")
    text = text.replace("리더스퀘어마곡", "리더스퀘어")
    text = text.replace("이너매스마곡1", "이너매스1")
    text = text.replace("우성에스비타워2", "우성SB2")
    text = text.replace("마곡에스비타워3", "우성SB3")
    text = text.replace("롯데캐슬르웨스트 제101동", "르웨스트웍스")
    text = text.replace("747타워", "747타워")
    text = text.replace("747", "747타워")
    text = text.replace("한양더챔버 1동", "한양더챔버")
    text = text.replace("마곡센트럴타워1", "센트럴타워1")

    text = text.replace("지상", "")

    text = text.replace("마곡엠밸리9단지 제판매시설2동", "엠밸리 9단지")
    text = text.replace("외 1필지 제원그로브업무", "원그로브")
    text = text.replace("퀸즈파크텐", "퀸즈10")
    text = text.replace("엠밸리더블유타워3", "W타워3")
    text = text.replace("웰튼메디플렉스", "웰튼병원")
    text = text.replace("문영퀸즈파크12차", "퀸즈12")
    text = text.replace("리더스타워마곡", "리더스타워")
    text = text.replace("마곡나루역보타닉비즈타워", "보타닉비즈타워")
    text = text.replace("마곡나루역 프라이빗타워 1", "안강1")
    text = text.replace("마곡엠밸리7단지", "엠밸리7단지")
    text = text.replace("외 2필지 델타빌딩", "델타빌딩")
    text = text.replace("문영퀸즈파크13", "퀸즈13")
    text = text.replace("홈앤쇼핑사옥", "홈앤쇼핑")
    text = text.replace("마곡동 그랑트윈타워 B동", "그랑트윈타워B동")
    text = text.replace("외 1필지 엔에이치서울축산농협엔에이치서울타워", "NH서울타워")
    text = text.replace("지엠지엘스타", "GMG엘스타")
    text = text.replace("케이스퀘어마곡업무시설", "케이스퀘어")
    text = text.replace("르웨스트시티 제본동", "르웨스트시티")
    text = text.replace("보타닉게이트마곡디38지식산업센터", "보타닉게이트")
    text = text.replace("외 3필지 마곡아이파크디어반", "아이파크디어반")
    text = text.replace("쿠쿠마곡빌딩", "쿠쿠빌딩")
    text = text.replace("마곡보타닉파크프라자를", "보타닉파크프라자")
    text = text.replace("엘케이빌딩", "LK빌딩")
    text = text.replace("에스에이치빌딩", "SH빌딩")
    text = text.replace("외 1필지 우림 블루나인 비즈니스센터", "우림블루나인")
    text = text.replace("외 1필지 원그로브업무", "원그로브")


    return text


def clean_building_name(raw):

    text = str(raw).strip()

    remove_words = [
        "건축물대장 면적 확인요청",
        "건축물대장 기준검수요청",
        "면적 확인요청",
        "면적확인요청",
        "기준검수요청",
        "건축물대장",
        "일부"
    ]

    for w in remove_words:
        text = text.replace(w, "")

    text = re.sub(r"^\d+\-\d+\s*", "", text)

    text = re.sub(r"제?\s*\d+\s*층", "", text)

    text = re.sub(r"제\s*(\d+호)", r"\1", text)

    text = normalize_dong(text)

    text = normalize_building_custom(text)

    if re.match(r"^\d+\s*(두산더랜드파크|센트럴타워2|에이스타워1|마곡엠밸리9단지|힐스테이트에코마곡역|나인스퀘어|원그로브|엠밸리 9단지|놀라움|델타빌딩|홈앤쇼핑|르웨스트시티|SH빌딩)", text):
      text = re.sub(r"^\d+\s*", "", text)

    text = " ".join(text.split())

    return text.strip()

def split_unit_numbers(text):
    text = text.replace("호", "")
    parts = re.split(r"[,\s]+", text)
    result = []

    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not p.endswith("호"):
            p = p + "호"
        result.append(p)

    return result



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
    property_type = request.args.get("property_type", "")

    query = Property.query

    if property_type:
        query = query.filter(Property.property_type == property_type)

    if mode == "sale":
        query = query.filter_by(category="매매")
    else:
        query = query.filter_by(category="월세")

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

    properties = query.all()

    last_upload = UploadLog.query.order_by(UploadLog.id.desc()).first()
    upload_time = last_upload.upload_time if last_upload else "업로드 기록 없음"

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
        "index.html",
        properties=properties,
        mode=mode,
        format_sale_price_korean=format_sale_price_korean,
        upload_time=upload_time,
        property_type=property_type,
        collections=collections,
        existing_pairs=existing_pairs,
        thumb_map=thumb_map
    )




@app.route("/search", methods=["GET"])
@login_required
def search():

    query = Property.query

    building = request.args.get("building", "")
    category = request.args.get("category", "")
    sort = request.args.get("sort", "")
    property_type = request.args.get("property_type", "")

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

    if property_type:
        query = query.filter(Property.property_type == property_type)

    if category == "월세":
        query = query.filter(Property.category == "월세")
    elif category == "매매":
        query = query.filter(Property.category == "매매")

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

    results = query.all()

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
        thumb_map=thumb_map
    )









    collections = Collection.query.all()

    return render_template(
        "search.html",
        properties=None,
        collections=collections,
        building=building,
        category=category,
        sort=sort,
        property_type=property_type,
        min_deposit=min_deposit,
        max_deposit=max_deposit,
        min_rent=min_rent,
        max_rent=max_rent,
        min_area=min_area,
        max_area=max_area
    )


@app.route("/register", methods=["GET", "POST"])
@login_required
def register():

    # -------- 빠른 매물 등록 --------
    if request.method == "POST" and request.form.get("form_type") == "quick":

        raw_text = request.form.get("raw_text")

        building, exclusive, contract, price = extract_info_from_text(raw_text)

        category, deposit, rent, sale = parse_price_auto(price)

        p = Property(
            building_name=building,
            exclusive_area=exclusive,
            contract_area=contract,
            deposit=deposit,
            rent=rent,
            sale_price=sale,
            category=category,
            property_type="사무실"
        )

        db.session.add(p)
        db.session.commit()

        return redirect(url_for("register"))
    
        # -------- 엑셀 최신화 --------
    if request.method == "POST" and request.form.get("form_type") == "excel":

        file = request.files.get("file")
        if not file:
            return "파일이 전달되지 않았습니다"

        filename = file.filename.lower()

        if filename.endswith(".csv"):
            df = pd.read_csv(file, encoding="cp949", dtype=str)
        else:
            df = pd.read_excel(file, dtype=str)

        df.columns = df.columns.str.strip()
        print("=====엑셀 컬럼 목록=====")
        print(list(df.columns))


        def find_col(keyword):
            for c in df.columns:
                if keyword in c:
                    return c
            return None

        col_address = find_col("주소")
        col_price = find_col("매물")
        col_exclusive = find_col("전용")
        col_contract = find_col("계약")
        col_type = find_col("종류")

        if not col_address:
            return "주소 컬럼을 찾지 못했습니다"

        Property.query.delete()
        db.session.commit()

        for _, row in df.iterrows():
        


            building = clean_building_name(row.get(col_address, ""))

            deal_type = str(row.get("거래종류", "")).strip()
            price_raw = str(row.get("매물가", "")).replace(",", "").strip()

            deposit = 0
            rent = 0
            sale = 0

            if deal_type == "월세":
                if "/" in price_raw:
                    left, right = price_raw.split("/", 1)
                    deposit = int(left) if left.isdigit() else 0
                    rent = int(right) if right.isdigit() else 0

            elif deal_type == "매매":
                sale = int(price_raw) if price_raw.isdigit() else 0

            p = Property(
                building_name=building,
                exclusive_area=to_pyung(row.get(col_exclusive, 0)),
                contract_area=to_pyung(row.get(col_contract, 0)),
                deposit=deposit,
                rent=rent,
                sale_price=sale,
                category=deal_type,
                property_type=convert_property_type(row.get(col_type, "")).strip()

            )

            db.session.add(p)

            db.session.commit()



        return redirect(url_for("register", updated=1))


    # ===== GET 진입시 화면 표시 =====
    last_upload = UploadLog.query.order_by(UploadLog.id.desc()).first()
    upload_time = last_upload.upload_time if last_upload else "-"

    properties = Property.query.order_by(Property.id.desc()).limit(50).all()

    total_count = Property.query.count()
    rent_count = Property.query.filter_by(category="월세").count()
    sale_count = Property.query.filter_by(category="매매").count()

    return render_template(
        "register.html",
        properties=properties,
        upload_time=upload_time,
        total_count=total_count,
        rent_count=rent_count,
        sale_count=sale_count
    )




   





@app.route("/delete_all")
@login_required
def delete_all():

    Property.query.delete()
    db.session.commit()

    return redirect(url_for("excel_upload"))






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

    return render_template(
        "collection_detail.html",
        collection=collection,
        properties=properties,
        sort=sort
    )


    for item in items:
        p = Property.query.get(item.property_id)
        if p:
            p.collection_item_id = item.id
            properties.append(p)

    return render_template(
        "collection_detail.html",
        collection=collection,
        properties=properties
    )


@app.route("/collections/remove/<int:collection_id>/<int:property_id>")
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

    data = request.get_json()
    memo = (data.get("memo") or "")[:200]

    collection.memo = memo
    db.session.commit()

    return jsonify({"result": "ok", "memo": memo})


@app.route("/api/collection/<int:id>/memo", methods=["DELETE"])
@login_required
def api_delete_memo(id):

    collection = Collection.query.get_or_404(id)

    collection.memo = None
    db.session.commit()

    return jsonify({"result": "ok"})


@app.route("/upload_images/<int:property_id>", methods=["POST"])
@login_required
def upload_images(property_id):

    files = request.files.getlist("images")

    if not files:
        return "no files", 400

    for file in files:
        if file.filename == "":
            continue

        filename = secure_filename(file.filename)
        unique = f"{datetime.utcnow().timestamp()}_{filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
        file.save(save_path)

        img = PropertyImage(
            property_id=property_id,
            file_path="/" + save_path.replace("\\","/")
        )
        db.session.add(img)

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




@app.route("/property/<int:id>")
@login_required
def property_detail(id):

    p = Property.query.get_or_404(id)

    images = PropertyImage.query.filter_by(property_id=id).order_by(PropertyImage.id.desc()).all()

    return render_template(
        "property_detail.html",
        p=p,
        images=images,
        format_sale_price_korean=format_sale_price_korean
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)



import streamlit as st
import pandas as pd
import os
import bcrypt
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, or_, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import NullPool
import cloudinary
import cloudinary.uploader
import plotly.express as px
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import tempfile

# ---------- CẤU HÌNH DATABASE (CHUẨN PRODUCTION) ----------
# Ưu tiên PostgreSQL từ secrets, nếu không thì SQLite local
if os.environ.get('STREAMLIT_CLOUD') or os.environ.get('STREAMLIT_RUNTIME'):
    try:
        DATABASE_URL = st.secrets["DATABASE_URL"]   # PostgreSQL URL
        use_postgres = True
    except:
        # Fallback SQLite (dùng file trong thư mục hiện tại, không /tmp)
        DATABASE_URL = "sqlite:///sales.db"
        use_postgres = False
else:
    DATABASE_URL = "sqlite:///sales.db"
    use_postgres = False

# Engine với NullPool cho SQLite (tránh lock) và pool_pre_ping cho PostgreSQL
if use_postgres:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=NullPool, echo=False)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# ---------- CLOUDINARY (CHỈ DÙNG SECRETS, KHÔNG HARDCODE) ----------
if os.environ.get('STREAMLIT_CLOUD') or os.environ.get('STREAMLIT_RUNTIME'):
    try:
        CLOUD_NAME = st.secrets["CLOUD_NAME"]
        API_KEY = st.secrets["API_KEY"]
        API_SECRET = st.secrets["API_SECRET"]
    except:
        st.error("❌ Thiếu Cloudinary secrets. Vui lòng cấu hình trên Streamlit Cloud.")
        st.stop()
else:
    # Khi chạy local, bạn có thể dùng biến môi trường hoặc hardcode tạm (nhưng không push lên git)
    # Tốt nhất dùng .env và load_dotenv, nhưng để đơn giản tôi đặt mặc định rỗng
    st.error("❌ Chạy local cần cấu hình Cloudinary. Vui lòng tạo file .env hoặc set biến môi trường.")
    st.stop()

cloudinary.config(cloud_name=CLOUD_NAME, api_key=API_KEY, api_secret=API_SECRET)

# ---------- CSS ----------
st.markdown("""
<style>
.block-container { padding-top: 1rem; }
.stButton button {
    border-radius: 10px;
    background-color: #4CAF50;
    color: white;
    font-weight: bold;
    border: none;
    transition: 0.2s;
}
.stButton button:hover { background-color: #45a049; }
.product-card {
    background: linear-gradient(145deg, #2c2c2c, #1f1f1f);
    border-radius: 15px;
    padding: 15px;
    text-align: center;
    box-shadow: 0 4px 10px rgba(0,0,0,0.3);
    margin-bottom: 15px;
}
.price { font-size: 1.3em; color: #4CAF50; font-weight: bold; }
.stock { color: #ff9800; }
</style>
""", unsafe_allow_html=True)

# ---------- MODELS ----------
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, nullable=False)
    image_url = Column(String)
    barcode = Column(String, unique=True, nullable=True)

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True)
    total_spent = Column(Float, default=0)
    total_purchases = Column(Integer, default=0)
    type = Column(String, default='regular')

class Sale(Base):
    __tablename__ = 'sales'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'))
    date = Column(DateTime, default=datetime.now)
    total_amount = Column(Float)
    discount = Column(Float)
    final_amount = Column(Float)
    customer = relationship("Customer")

class SaleItem(Base):
    __tablename__ = 'sale_items'
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey('sales.id'))
    product_id = Column(Integer, ForeignKey('products.id'))
    quantity = Column(Integer)
    price = Column(Float)

class Setting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)

# Tạo bảng an toàn
try:
    Base.metadata.create_all(engine)
except Exception as e:
    st.error(f"Lỗi tạo bảng: {e}")
    st.stop()

# ---------- HÀM TIỆN ÍCH ----------
def hash_password(pwd): return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
def verify_password(pwd, hashed): return bcrypt.checkpw(pwd.encode(), hashed.encode())

def init_data():
    with SessionLocal() as s:
        if not s.query(User).filter_by(username='admin').first():
            s.add_all([User(username='admin', password_hash=hash_password('admin123'), role='admin'),
                       User(username='staff', password_hash=hash_password('staff123'), role='staff')])
        defaults = {'loyal_min_spent':'5000000','loyal_min_purchases':'10','longtime_min_spent':'2000000',
                    'longtime_min_purchases':'5','loyal_discount':'5','longtime_discount':'2','regular_discount':'0'}
        for k,v in defaults.items():
            if not s.query(Setting).filter_by(key=k).first():
                s.add(Setting(key=k, value=v))
        s.commit()

# Khởi tạo dữ liệu an toàn
try:
    init_data()
except Exception as e:
    st.error(f"Lỗi khởi tạo dữ liệu: {e}")
    st.stop()

def upload_image(file): return cloudinary.uploader.upload(file, folder="sales_app")['secure_url']

# Cache ngắn (TTL=2s) chỉ cho danh sách sản phẩm (không stock vì stock thay đổi nhanh)
@st.cache_data(ttl=2, show_spinner=False)
def get_products(search=""):
    with SessionLocal() as s:
        q = s.query(Product)
        if search: q = q.filter(or_(Product.name.contains(search), Product.barcode.contains(search)))
        # Lưu ý: stock được lấy từ DB mỗi lần, không cache stock riêng
        return [{'id':p.id,'name':p.name,'price':p.price,'stock':p.stock,'image_url':p.image_url,'barcode':p.barcode} for p in q.all()]

@st.cache_data(ttl=10, show_spinner=False)
def get_customers():
    with SessionLocal() as s: return [{'id':c.id,'name':c.name,'phone':c.phone,'total_spent':c.total_spent,'total_purchases':c.total_purchases,'type':c.type} for c in s.query(Customer).all()]

@st.cache_data(ttl=10, show_spinner=False)
def get_loyal(): return [{'name':c.name,'phone':c.phone,'total_spent':c.total_spent} for c in SessionLocal().query(Customer).filter_by(type='loyal').all()]

@st.cache_data(ttl=10, show_spinner=False)
def get_vip(limit=10): return [{'name':c.name,'phone':c.phone,'total_spent':c.total_spent,'type':c.type} for c in SessionLocal().query(Customer).order_by(Customer.total_spent.desc()).limit(limit).all()]

@st.cache_data(ttl=10, show_spinner=False)
def get_sales(): return [{'id':s.id,'date':s.date,'final_amount':s.final_amount} for s in SessionLocal().query(Sale).all()]

@st.cache_data(ttl=10, show_spinner=False)
def get_top_products():
    with SessionLocal() as s:
        items = s.query(SaleItem.product_id, func.sum(SaleItem.quantity).label('qty')).group_by(SaleItem.product_id).all()
        if not items: return []
        prods = s.query(Product).filter(Product.id.in_([i[0] for i in items])).all()
        pmap = {p.id:p.name for p in prods}
        return sorted([{'name':pmap[pid],'total_qty':qty} for pid,qty in items], key=lambda x:x['total_qty'], reverse=True)[:10]

@st.cache_data(ttl=10, show_spinner=False)
def get_settings(): return {k.value:v.value for k,v in SessionLocal().query(Setting).all()}

def clear_cache(): st.cache_data.clear()

# ---------------- NGHIỆP VỤ GHI (CÓ ROW LOCK NẾU POSTGRES) ----------------
def add_product(name,price,stock,img,barcode):
    with SessionLocal() as s:
        s.add(Product(name=name,price=price,stock=stock,image_url=upload_image(img) if img else "",barcode=barcode))
        s.commit()
    clear_cache()

def update_product(pid,name,price,stock,img,barcode):
    with SessionLocal() as s:
        p = s.get(Product, pid)
        if p:
            p.name, p.price, p.stock, p.barcode = name, price, stock, barcode
            if img: p.image_url = upload_image(img)
            s.commit()
    clear_cache()

def delete_product(pid):
    with SessionLocal() as s:
        s.query(Product).filter_by(id=pid).delete()
        s.commit()
    clear_cache()

def add_customer(name,phone):
    with SessionLocal() as s:
        s.add(Customer(name=name,phone=phone))
        s.commit()
    clear_cache()

def update_customer_type(cid):
    with SessionLocal() as s:
        c = s.get(Customer, cid)
        if c:
            sets = get_settings()
            loyal_spent = float(sets.get('loyal_min_spent',5000000))
            loyal_pur = int(sets.get('loyal_min_purchases',10))
            longtime_spent = float(sets.get('longtime_min_spent',2000000))
            longtime_pur = int(sets.get('longtime_min_purchases',5))
            if c.total_spent >= loyal_spent and c.total_purchases >= loyal_pur: c.type = 'loyal'
            elif c.total_spent >= longtime_spent and c.total_purchases >= longtime_pur: c.type = 'longtime'
            else: c.type = 'regular'
            s.commit()
    clear_cache()

def get_discount(cid):
    with SessionLocal() as s:
        c = s.get(Customer, cid)
        if not c: return 0
        return float(get_settings().get(f"{c.type}_discount",0))

def record_sale(cid, cart_items, disc_percent):
    with SessionLocal() as s:
        try:
            # Nếu dùng PostgreSQL, thực hiện row lock
            for pid, qty, price in cart_items:
                if use_postgres:
                    p = s.query(Product).filter_by(id=pid).with_for_update().first()
                else:
                    p = s.get(Product, pid)
                if not p or p.stock < qty:
                    raise ValueError(f"Sản phẩm {p.name if p else '?'} không đủ hàng")
            total = sum(q*p for _,q,p in cart_items)
            disc_amt = total * disc_percent / 100
            final = total - disc_amt
            sale = Sale(customer_id=cid, total_amount=total, discount=disc_amt, final_amount=final)
            s.add(sale)
            s.flush()
            for pid, qty, price in cart_items:
                s.add(SaleItem(sale_id=sale.id, product_id=pid, quantity=qty, price=price))
                s.query(Product).filter_by(id=pid).update({Product.stock: Product.stock - qty})
            c = s.get(Customer, cid)
            c.total_spent += final
            c.total_purchases += 1
            s.commit()
            update_customer_type(cid)
            clear_cache()
            return sale.id, final, disc_amt
        except Exception as e:
            s.rollback()
            raise e

def upload_csv(file):
    df = pd.read_csv(file)
    with SessionLocal() as s:
        for _,r in df.iterrows():
            name, phone = r['name'], str(r['phone'])
            spent = float(r.get('total_spent',0))
            purchases = int(r.get('total_purchases',0))
            cust = s.query(Customer).filter_by(phone=phone).first()
            if cust: cust.total_spent, cust.total_purchases = spent, purchases
            else: s.add(Customer(name=name, phone=phone, total_spent=spent, total_purchases=purchases))
        s.commit()
    for c in get_customers(): update_customer_type(c['id'])
    clear_cache()

# ---------- PDF VỚI REPORTLAB (HỖ TRỢ TIẾNG VIỆT) ----------
def gen_pdf(sale_id, cus_name, cus_phone, cus_type, items, total, discount, final):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    # Đăng ký font Unicode (cần có file DejaVuSans.ttf trong thư mục fonts)
    font_path = "fonts/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('DejaVu', font_path))
        c.setFont('DejaVu', 12)
    else:
        c.setFont('Helvetica', 12)
    # Tiêu đề
    c.drawString(50, height - 50, "HÓA ĐƠN BÁN HÀNG")
    c.drawString(50, height - 70, f"Mã HD: {sale_id}")
    c.drawString(50, height - 90, f"Khách hàng: {cus_name} - {cus_phone} ({cus_type})")
    c.drawString(50, height - 110, f"Ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y = height - 140
    # Bảng
    c.drawString(50, y, "Sản phẩm")
    c.drawString(200, y, "SL")
    c.drawString(250, y, "Đơn giá")
    c.drawString(320, y, "Thành tiền")
    y -= 20
    for it in items:
        c.drawString(50, y, it['name'][:30])
        c.drawString(200, y, str(it['qty']))
        c.drawString(250, y, f"{int(it['price']):,}")
        c.drawString(320, y, f"{int(it['qty']*it['price']):,}")
        y -= 20
        if y < 50:
            c.showPage()
            y = height - 50
    y -= 20
    c.drawString(50, y, f"Tổng tiền: {int(total):,} VNĐ")
    y -= 20
    c.drawString(50, y, f"Giảm giá: {int(discount):,} VNĐ")
    y -= 20
    c.setFont('Helvetica-Bold', 12)
    c.drawString(50, y, f"Thực thu: {int(final):,} VNĐ")
    c.save()
    buffer.seek(0)
    return buffer

# ---------- LOGIN & SESSION TIMEOUT ----------
def login(username, password):
    with SessionLocal() as s:
        u = s.query(User).filter_by(username=username).first()
        if u and verify_password(password, u.password_hash): return u.role
    return None

def get_or_create_guest():
    with SessionLocal() as s:
        guest = s.query(Customer).filter_by(phone="0000000000").first()
        if not guest:
            guest = Customer(name="Khách lẻ", phone="0000000000")
            s.add(guest)
            s.commit()
        return guest.id

# ---------- STREAMLIT APP ----------
st.set_page_config(page_title="Hệ thống bán hàng Pro", layout="wide")

# Khởi tạo session state
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'role' not in st.session_state: st.session_state.role = None
if 'cart' not in st.session_state: st.session_state.cart = []
if 'sale_step' not in st.session_state: st.session_state.sale_step = 1
if 'search' not in st.session_state: st.session_state.search = ""
if 'current_customer' not in st.session_state: st.session_state.current_customer = get_or_create_guest()
if 'barcode_scanner' not in st.session_state: st.session_state.barcode_scanner = ""
if 'last_active' not in st.session_state: st.session_state.last_active = datetime.now()

# Session timeout (30 phút)
if st.session_state.logged_in:
    if (datetime.now() - st.session_state.last_active).seconds > 1800:
        st.session_state.logged_in = False
        st.warning("Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.")
        st.rerun()
    else:
        st.session_state.last_active = datetime.now()

if not st.session_state.logged_in:
    st.title("🔐 Đăng nhập")
    with st.form("login"):
        uname = st.text_input("Tên đăng nhập")
        pwd = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Đăng nhập"):
            role = login(uname, pwd)
            if role:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.rerun()
            else: st.error("Sai tên hoặc mật khẩu")
    st.stop()

menu = st.sidebar.radio("Chức năng", ["🏠 Trang chủ", "📦 Sản phẩm", "🛒 Bán hàng", "👥 Khách hàng", "🔥 Khách thân thiết", "📊 Dashboard", "⚙️ Cài đặt (Admin)"])

# -------------------- ADMIN --------------------
if st.session_state.role == 'admin':
    if menu == "⚙️ Cài đặt (Admin)":
        st.header("Cài đặt")
        sets = get_settings()
        with st.form("settings"):
            loyal_spent = st.number_input("Ngưỡng chi tiêu - Thân thiết", value=float(sets.get('loyal_min_spent',5000000)), step=100000, format="%d")
            loyal_pur = st.number_input("Số lần mua - Thân thiết", value=int(sets.get('loyal_min_purchases',10)), step=1)
            longtime_spent = st.number_input("Ngưỡng chi tiêu - Lâu năm", value=float(sets.get('longtime_min_spent',2000000)), step=100000, format="%d")
            longtime_pur = st.number_input("Số lần mua - Lâu năm", value=int(sets.get('longtime_min_purchases',5)), step=1)
            loyal_disc = st.number_input("Giảm giá (%) - Thân thiết", value=float(sets.get('loyal_discount',5)), step=0.5)
            longtime_disc = st.number_input("Giảm giá (%) - Lâu năm", value=float(sets.get('longtime_discount',2)), step=0.5)
            regular_disc = st.number_input("Giảm giá (%) - Thường", value=float(sets.get('regular_discount',0)), step=0.5)
            if st.form_submit_button("Lưu"):
                with SessionLocal() as s:
                    for k,v in [('loyal_min_spent',loyal_spent),('loyal_min_purchases',loyal_pur),('longtime_min_spent',longtime_spent),
                                ('longtime_min_purchases',longtime_pur),('loyal_discount',loyal_disc),('longtime_discount',longtime_disc),
                                ('regular_discount',regular_disc)]:
                        s.query(Setting).filter_by(key=k).first().value = str(v)
                    s.commit()
                clear_cache()
                st.success("Đã lưu"); st.rerun()
        st.subheader("Tải CSV khách hàng")
        up = st.file_uploader("File CSV (name, phone, total_spent, total_purchases)", type="csv")
        if up: upload_csv(up); st.success("Đã cập nhật")

    elif menu == "📦 Sản phẩm":
        st.header("Quản lý sản phẩm")
        tab1, tab2 = st.tabs(["Thêm", "Sửa/Xóa"])
        with tab1:
            with st.form("add"):
                name = st.text_input("Tên")
                price = st.number_input("Giá", min_value=0.0, step=1000.0, format="%d")
                stock = st.number_input("Số lượng", min_value=0, step=1)
                barcode = st.text_input("Mã vạch")
                img = st.file_uploader("Ảnh", type=['png','jpg','jpeg'])
                if st.form_submit_button("Thêm"):
                    if name and price>0: add_product(name, price, stock, img, barcode); st.success("Đã thêm"); st.rerun()
        with tab2:
            prods = get_products()
            if prods:
                sel = st.selectbox("Chọn", [f"{p['id']} - {p['name']}" for p in prods])
                p = next(x for x in prods if f"{x['id']} - {x['name']}" == sel)
                with st.form("edit"):
                    nname = st.text_input("Tên", p['name'])
                    nprice = st.number_input("Giá", value=p['price'], step=1000.0, format="%d")
                    nstock = st.number_input("Tồn kho", value=p['stock'], step=1)
                    nbarcode = st.text_input("Mã vạch", value=p.get('barcode',''))
                    nimg = st.file_uploader("Ảnh mới", type=['png','jpg','jpeg'])
                    if st.form_submit_button("Cập nhật"):
                        update_product(p['id'], nname, nprice, nstock, nimg, nbarcode); st.success("Đã cập nhật"); st.rerun()
                if st.button("Xóa"): delete_product(p['id']); st.rerun()
            else: st.info("Chưa có sản phẩm")

    elif menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng")
        df = pd.DataFrame(get_customers())
        if not df.empty: df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(df)
        else: st.info("Chưa có")

    elif menu == "🔥 Khách thân thiết":
        st.header("Khách thân thiết")
        df = pd.DataFrame(get_loyal())
        if not df.empty: df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(df)
        else: st.info("Chưa có")
        st.subheader("Top 10 VIP")
        dfv = pd.DataFrame(get_vip())
        if not dfv.empty: dfv['total_spent'] = dfv['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(dfv)

    elif menu == "📊 Dashboard":
        st.header("Thống kê")
        sales = get_sales()
        if sales:
            total = sum(s['final_amount'] for s in sales)
            c1,c2,c3 = st.columns(3)
            c1.metric("Doanh thu", f"{int(total):,} VNĐ")
            c2.metric("Số đơn", len(sales))
            c3.metric("Khách hàng", len(get_customers()))
            df = pd.DataFrame(sales)
            df['date'] = pd.to_datetime(df['date']).dt.date
            df = df.groupby('date')['final_amount'].sum().reset_index()
            st.plotly_chart(px.line(df, x='date', y='final_amount', title='Doanh thu theo ngày'), use_container_width=True)
            top = get_top_products()
            if top: st.plotly_chart(px.bar(pd.DataFrame(top), x='name', y='total_qty', title='Top sản phẩm'), use_container_width=True)
        else: st.info("Chưa có dữ liệu")

    elif menu == "🏠 Trang chủ": st.header("Tổng quan Admin")

# -------------------- NHÂN VIÊN --------------------
else:
    if menu == "🏠 Trang chủ": st.header("Chào mừng nhân viên")
    elif menu == "📦 Sản phẩm":
        st.header("Thêm sản phẩm")
        with st.form("staff_add"):
            name = st.text_input("Tên")
            price = st.number_input("Giá", min_value=0.0, step=1000.0, format="%d")
            stock = st.number_input("Số lượng", min_value=0, step=1)
            barcode = st.text_input("Mã vạch")
            img = st.file_uploader("Ảnh", type=['png','jpg','jpeg'])
            if st.form_submit_button("Thêm"):
                if name and price>0: add_product(name, price, stock, img, barcode); st.success("Đã thêm"); st.rerun()
        st.subheader("Danh sách sản phẩm")
        prods = get_products()
        if prods:
            cols = st.columns(4)
            for i,p in enumerate(prods):
                with cols[i%4]:
                    if p['image_url']: st.image(p['image_url'], use_container_width=True)
                    st.markdown(f"<div class='product-card'><h4>{p['name']}</h4><p class='price'>{int(p['price']):,}đ</p><p class='stock'>📦 Tồn: {p['stock']}</p></div>", unsafe_allow_html=True)
        else: st.info("Chưa có sản phẩm")

    elif menu == "🛒 Bán hàng":
        st.header("Bán hàng - Quét mã vạch / Chọn sản phẩm")

        # Ô quét mã vạch
        barcode_scanned = st.text_input("📷 Quét mã vạch (hoặc nhập)", key="barcode_scanner", placeholder="Đưa mã vạch vào đây...")
        if barcode_scanned:
            with SessionLocal() as s:
                prod = s.query(Product).filter_by(barcode=barcode_scanned).first()
                if prod:
                    found = False
                    for item in st.session_state.cart:
                        if item['id'] == prod.id:
                            item['qty'] += 1
                            found = True
                            break
                    if not found:
                        st.session_state.cart.append({
                            'id': prod.id,
                            'name': prod.name,
                            'price': prod.price,
                            'qty': 1
                        })
                    st.success(f"Đã thêm {prod.name}")
                else:
                    st.warning("Không tìm thấy sản phẩm")
            st.session_state.barcode_scanner = ""
            st.rerun()

        # Giỏ hàng
        st.subheader("🛒 Giỏ hàng")
        if st.session_state.cart:
            total = 0
            for idx, it in enumerate(st.session_state.cart):
                col1, col2, col3, col4, col5 = st.columns([3,1,1,1,1])
                col1.write(f"**{it['name']}** - {int(it['price']):,}đ")
                col2.write(f"SL: {it['qty']}")
                if col3.button("➕", key=f"inc_{idx}"):
                    prod = next((p for p in get_products() if p['id'] == it['id']), None)
                    if prod and it['qty'] < prod['stock']:
                        it['qty'] += 1
                        st.rerun()
                    else:
                        st.warning("Không đủ hàng")
                if col4.button("➖", key=f"dec_{idx}"):
                    if it['qty'] > 1:
                        it['qty'] -= 1
                        st.rerun()
                    else:
                        st.session_state.cart.pop(idx)
                        st.rerun()
                if col5.button("❌", key=f"del_{idx}"):
                    st.session_state.cart.pop(idx)
                    st.rerun()
                total += it['price'] * it['qty']

            disc_percent = get_discount(st.session_state.current_customer)
            disc_amt = total * disc_percent / 100
            final = total - disc_amt

            colA, colB, colC = st.columns(3)
            colA.metric("Tổng tiền", f"{int(total):,} VNĐ")
            colB.metric(f"Giảm giá ({disc_percent}%)", f"-{int(disc_amt):,} VNĐ")
            colC.metric("Thực thu", f"{int(final):,} VNĐ")

            colX, colY = st.columns(2)
            with colX:
                if st.button("✅ Thanh toán", use_container_width=True):
                    cart_items = [(it['id'], it['qty'], it['price']) for it in st.session_state.cart]
                    try:
                        sale_id, f_amt, d_amt = record_sale(st.session_state.current_customer, cart_items, disc_percent)
                        st.success(f"Thanh toán thành công! Hóa đơn #{sale_id}")
                        cus = next((c for c in get_customers() if c['id'] == st.session_state.current_customer), None)
                        if cus:
                            pdf = gen_pdf(sale_id, cus['name'], cus['phone'], cus['type'], st.session_state.cart, total, d_amt, f_amt)
                            st.download_button("📄 Tải hóa đơn PDF", pdf, f"invoice_{sale_id}.pdf", "application/pdf")
                        st.session_state.cart = []
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with colY:
                if st.button("🗑 Hủy đơn", use_container_width=True):
                    st.session_state.cart = []
                    st.rerun()
        else:
            st.info("Giỏ hàng trống")

        # Danh sách sản phẩm
        st.markdown("---")
        st.subheader("📦 Chọn sản phẩm từ danh sách")
        search = st.text_input("🔍 Tìm kiếm theo tên hoặc mã vạch", value=st.session_state.search, key="search_box")
        if search != st.session_state.search:
            st.session_state.search = search
            st.rerun()

        products = get_products(st.session_state.search)
        if products:
            cols = st.columns(4)
            for i, p in enumerate(products):
                with cols[i % 4]:
                    if p['image_url']:
                        st.image(p['image_url'], use_container_width=True)
                    st.markdown(f"<div class='product-card'><h4>{p['name']}</h4><p class='price'>{int(p['price']):,}đ</p><p class='stock'>📦 Tồn: {p['stock']}</p></div>", unsafe_allow_html=True)
                    qty = st.number_input("SL", min_value=1, max_value=p['stock'], value=1, key=f"qty_{p['id']}", label_visibility="collapsed")
                    if st.button(f"➕ Thêm {p['name']}", key=f"add_{p['id']}"):
                        found = False
                        for item in st.session_state.cart:
                            if item['id'] == p['id']:
                                new_qty = item['qty'] + qty
                                if new_qty <= p['stock']:
                                    item['qty'] = new_qty
                                else:
                                    st.warning("Vượt quá tồn kho")
                                found = True
                                break
                        if not found:
                            st.session_state.cart.append({
                                'id': p['id'],
                                'name': p['name'],
                                'price': p['price'],
                                'qty': qty
                            })
                        st.rerun()
        else:
            st.info("Không tìm thấy sản phẩm")

    elif menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng")
        df = pd.DataFrame(get_customers())
        if not df.empty: df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(df)
        else: st.info("Chưa có")

    elif menu == "🔥 Khách thân thiết":
        st.header("Khách thân thiết")
        df = pd.DataFrame(get_loyal())
        if not df.empty: df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(df)
        else: st.info("Chưa có")
        st.subheader("Top 10 VIP")
        dfv = pd.DataFrame(get_vip())
        if not dfv.empty: dfv['total_spent'] = dfv['total_spent'].apply(lambda x: f"{int(x):,}"); st.dataframe(dfv)

    elif menu == "📊 Báo cáo":
        st.header("Lịch sử bán hàng")
        df = pd.DataFrame(get_sales())
        if not df.empty: df['final_amount'] = df['final_amount'].apply(lambda x: f"{int(x):,}"); st.dataframe(df)
        else: st.info("Chưa có hóa đơn")

# Đăng xuất
if st.sidebar.button("Đăng xuất"):
    for k in list(st.session_state.keys()): del st.session_state[k]
    st.rerun()

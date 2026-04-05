import streamlit as st
import pandas as pd
import os
import bcrypt
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, or_, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import cloudinary
import cloudinary.uploader
import plotly.express as px
from fpdf import FPDF
import io
import tempfile

# ---------- CẤU HÌNH DATABASE (SQLite) ----------
if os.environ.get('STREAMLIT_CLOUD'):
    DB_PATH = os.path.join(tempfile.gettempdir(), 'sales.db')
else:
    DB_PATH = 'sales.db'

DATABASE_URL = f"sqlite:///{DB_PATH}"
use_row_lock = False

# Engine tối ưu
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
    future=True
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# ---------- CẤU HÌNH CLOUDINARY ----------
if os.environ.get('STREAMLIT_CLOUD'):
    try:
        CLOUD_NAME = st.secrets["CLOUD_NAME"]
        API_KEY = st.secrets["API_KEY"]
        API_SECRET = st.secrets["API_SECRET"]
    except:
        st.error("❌ Chưa cấu hình Cloudinary trong Secrets")
        st.stop()
else:
    # Thay bằng thông tin thật của bạn
    CLOUD_NAME = "dw6f9wege"
    API_KEY = "353532489943778"
    API_SECRET = "cZWPsYQBsJ-y5g2fXLj8WUW7X-w"

cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=API_KEY,
    api_secret=API_SECRET
)

# ---------- CSS GIAO DIỆN ----------
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button {
        border-radius: 10px;
        background-color: #4CAF50;
        color: white;
        font-weight: bold;
    }
    .stButton button:hover { background-color: #45a049; }
    .card {
        padding: 15px;
        border-radius: 15px;
        background: #2d2d2d;
        margin-bottom: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .product-card {
        background: #2d2d2d;
        border-radius: 15px;
        padding: 15px;
        text-align: center;
        transition: transform 0.2s;
    }
    .product-card:hover { transform: scale(1.02); }
    .price { font-size: 1.2em; color: #4CAF50; font-weight: bold; }
    .stock { color: #ff9800; }
    hr { margin: 0.5rem 0; }
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

Base.metadata.create_all(engine)

# ---------- HÀM HỖ TRỢ ----------
def hash_password(pwd: str) -> str:
    return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

def verify_password(pwd: str, hashed: str) -> bool:
    return bcrypt.checkpw(pwd.encode(), hashed.encode())

def init_data():
    with SessionLocal() as session:
        if not session.query(User).filter_by(username='admin').first():
            admin = User(username='admin', password_hash=hash_password('admin123'), role='admin')
            staff = User(username='staff', password_hash=hash_password('staff123'), role='staff')
            session.add_all([admin, staff])
        defaults = {
            'loyal_min_spent': '5000000', 'loyal_min_purchases': '10',
            'longtime_min_spent': '2000000', 'longtime_min_purchases': '5',
            'loyal_discount': '5', 'longtime_discount': '2', 'regular_discount': '0'
        }
        for k, v in defaults.items():
            if not session.query(Setting).filter_by(key=k).first():
                session.add(Setting(key=k, value=v))
        session.commit()

init_data()

def upload_image_to_cloudinary(image_file):
    result = cloudinary.uploader.upload(image_file, folder="sales_app")
    return result['secure_url']

# ---------- CACHE ----------
@st.cache_data(ttl=60)
def get_all_products_cached(search_term=""):
    with SessionLocal() as session:
        query = session.query(Product)
        if search_term:
            query = query.filter(or_(Product.name.contains(search_term), Product.barcode.contains(search_term)))
        products = query.all()
        return [{'id': p.id, 'name': p.name, 'price': p.price, 'stock': p.stock, 'image_url': p.image_url, 'barcode': p.barcode} for p in products]

@st.cache_data(ttl=60)
def get_customers_cached():
    with SessionLocal() as session:
        customers = session.query(Customer).all()
        return [{'id': c.id, 'name': c.name, 'phone': c.phone, 'total_spent': c.total_spent, 'total_purchases': c.total_purchases, 'type': c.type} for c in customers]

@st.cache_data(ttl=60)
def get_loyal_customers_cached():
    with SessionLocal() as session:
        customers = session.query(Customer).filter_by(type='loyal').all()
        return [{'name': c.name, 'phone': c.phone, 'total_spent': c.total_spent, 'total_purchases': c.total_purchases} for c in customers]

@st.cache_data(ttl=60)
def get_top_vip_customers_cached(limit=10):
    with SessionLocal() as session:
        customers = session.query(Customer).order_by(Customer.total_spent.desc()).limit(limit).all()
        return [{'name': c.name, 'phone': c.phone, 'total_spent': c.total_spent, 'total_purchases': c.total_purchases, 'type': c.type} for c in customers]

@st.cache_data(ttl=60)
def get_sales_data():
    with SessionLocal() as session:
        sales = session.query(Sale).all()
        return [{'id': s.id, 'date': s.date, 'final_amount': s.final_amount} for s in sales]

@st.cache_data(ttl=60)
def get_top_products_sold(limit=10):
    with SessionLocal() as session:
        items = session.query(SaleItem.product_id, func.sum(SaleItem.quantity).label('total_qty')).group_by(SaleItem.product_id).all()
        if not items:
            return []
        prod_ids = [i[0] for i in items]
        qties = [i[1] for i in items]
        products = session.query(Product).filter(Product.id.in_(prod_ids)).all()
        prod_map = {p.id: p.name for p in products}
        result = [{'name': prod_map[pid], 'total_qty': qty} for pid, qty in zip(prod_ids, qties)]
        result.sort(key=lambda x: x['total_qty'], reverse=True)
        return result[:limit]

@st.cache_data(ttl=60)
def get_settings():
    with SessionLocal() as session:
        return {s.key: s.value for s in session.query(Setting).all()}

def clear_cache():
    st.cache_data.clear()

# ---------- NGHIỆP VỤ GHI ----------
def add_product(name, price, stock, image_file, barcode=None):
    with SessionLocal() as session:
        image_url = upload_image_to_cloudinary(image_file) if image_file else ""
        product = Product(name=name, price=price, stock=stock, image_url=image_url, barcode=barcode)
        session.add(product)
        session.commit()
    clear_cache()

def update_product(product_id, name, price, stock, image_file=None, barcode=None):
    with SessionLocal() as session:
        product = session.query(Product).filter_by(id=product_id).first()
        if product:
            product.name = name
            product.price = price
            product.stock = stock
            if barcode:
                product.barcode = barcode
            if image_file:
                product.image_url = upload_image_to_cloudinary(image_file)
            session.commit()
    clear_cache()

def delete_product(product_id):
    with SessionLocal() as session:
        session.query(Product).filter_by(id=product_id).delete()
        session.commit()
    clear_cache()

def add_customer(name, phone):
    with SessionLocal() as session:
        cust = Customer(name=name, phone=phone)
        session.add(cust)
        session.commit()
    clear_cache()

def update_customer_type(customer_id):
    with SessionLocal() as session:
        cust = session.query(Customer).filter_by(id=customer_id).first()
        if cust:
            settings = get_settings()
            loyal_spent = float(settings.get('loyal_min_spent', 5000000))
            loyal_pur = int(settings.get('loyal_min_purchases', 10))
            longtime_spent = float(settings.get('longtime_min_spent', 2000000))
            longtime_pur = int(settings.get('longtime_min_purchases', 5))
            if cust.total_spent >= loyal_spent and cust.total_purchases >= loyal_pur:
                cust.type = 'loyal'
            elif cust.total_spent >= longtime_spent and cust.total_purchases >= longtime_pur:
                cust.type = 'longtime'
            else:
                cust.type = 'regular'
            session.commit()
    clear_cache()

def get_discount_for_customer(customer_id):
    with SessionLocal() as session:
        cust = session.query(Customer).filter_by(id=customer_id).first()
        if not cust:
            return 0
        settings = get_settings()
        key = f"{cust.type}_discount"
        disc = float(settings.get(key, 0))
    return disc

def record_sale(customer_id, cart_items, discount_percent):
    with SessionLocal() as session:
        try:
            # Kiểm tra tồn kho
            for pid, qty, price in cart_items:
                product = session.query(Product).filter_by(id=pid).first()
                if not product or product.stock < qty:
                    raise ValueError(f"Sản phẩm {product.name if product else '?'} không đủ hàng")
            total = sum(q * p for _, q, p in cart_items)
            discount_amount = total * discount_percent / 100
            final = total - discount_amount
            sale = Sale(customer_id=customer_id, total_amount=total, discount=discount_amount, final_amount=final)
            session.add(sale)
            session.flush()
            for pid, qty, price in cart_items:
                item = SaleItem(sale_id=sale.id, product_id=pid, quantity=qty, price=price)
                session.add(item)
                session.query(Product).filter_by(id=pid).update({Product.stock: Product.stock - qty})
            cust = session.query(Customer).filter_by(id=customer_id).first()
            cust.total_spent += final
            cust.total_purchases += 1
            session.commit()
            update_customer_type(customer_id)
            clear_cache()
            return sale.id, final, discount_amount
        except Exception as e:
            session.rollback()
            raise e

def upload_customers_csv(file):
    df = pd.read_csv(file)
    with SessionLocal() as session:
        for _, row in df.iterrows():
            name = row.get('name')
            phone = str(row.get('phone'))
            spent = float(row.get('total_spent', 0))
            purchases = int(row.get('total_purchases', 0))
            cust = session.query(Customer).filter_by(phone=phone).first()
            if cust:
                cust.total_spent = spent
                cust.total_purchases = purchases
            else:
                cust = Customer(name=name, phone=phone, total_spent=spent, total_purchases=purchases)
                session.add(cust)
        session.commit()
    with SessionLocal() as session:
        for cust in session.query(Customer).all():
            update_customer_type(cust.id)
    clear_cache()

def generate_pdf_invoice(sale_id, customer_name, customer_phone, customer_type, items, total, discount, final):
    font_path = "fonts/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdf = FPDF()
        pdf.add_font('DejaVu', '', font_path, uni=True)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font('DejaVu', '', 12)
    else:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="HÓA ĐƠN BÁN HÀNG", ln=1, align='C')
    pdf.cell(200, 10, txt=f"Mã HD: {sale_id}", ln=1)
    pdf.cell(200, 10, txt=f"Khách hàng: {customer_name} - {customer_phone} ({customer_type})", ln=1)
    pdf.cell(200, 10, txt=f"Ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=1)
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(80, 10, "Sản phẩm", 1)
    pdf.cell(30, 10, "SL", 1)
    pdf.cell(40, 10, "Đơn giá", 1)
    pdf.cell(40, 10, "Thành tiền", 1)
    pdf.ln()
    pdf.set_font('Arial', size=10)
    for item in items:
        pdf.cell(80, 10, item['name'], 1)
        pdf.cell(30, 10, str(item['qty']), 1)
        pdf.cell(40, 10, f"{int(item['price'])}", 1)  # loại bỏ .00
        pdf.cell(40, 10, f"{int(item['qty']*item['price'])}", 1)
        pdf.ln()
    pdf.ln(5)
    pdf.cell(200, 10, txt=f"Tổng tiền: {int(total)} VNĐ", ln=1)
    pdf.cell(200, 10, txt=f"Giảm giá: {int(discount)} VNĐ", ln=1)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(200, 10, txt=f"Thực thu: {int(final)} VNĐ", ln=1)
    pdf_output = io.BytesIO()
    pdf_output.write(pdf.output(dest='S').encode('latin1'))
    pdf_output.seek(0)
    return pdf_output

# ---------- LOGIN ----------
def login(username, password):
    with SessionLocal() as session:
        user = session.query(User).filter_by(username=username).first()
        if user and verify_password(password, user.password_hash):
            return user.role
    return None

# ---------- STREAMLIT APP ----------
st.set_page_config(page_title="Hệ thống bán hàng Pro", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'cart' not in st.session_state:
    st.session_state.cart = []  # mỗi item: {'id', 'name', 'price', 'qty'}
if 'sale_step' not in st.session_state:
    st.session_state.sale_step = 1
if 'search_term' not in st.session_state:
    st.session_state.search_term = ""
if 'current_customer' not in st.session_state:
    st.session_state.current_customer = None

if not st.session_state.logged_in:
    st.title("🔐 Đăng nhập")
    with st.form("login_form"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Đăng nhập"):
            role = login(username, password)
            if role:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.rerun()
            else:
                st.error("Sai tên hoặc mật khẩu")
    st.stop()

# Menu chính
menu = st.sidebar.radio("Chức năng", 
    ["🏠 Trang chủ", "📦 Sản phẩm", "🛒 Bán hàng", "👥 Khách hàng", "🔥 Khách thân thiết", "📊 Dashboard", "⚙️ Cài đặt (Admin)"])

# -------------------- ADMIN --------------------
if st.session_state.role == 'admin':
    if menu == "⚙️ Cài đặt (Admin)":
        st.header("Cài đặt hệ thống")
        settings = get_settings()
        with st.form("settings_form"):
            loyal_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) - Khách Thân thiết", value=float(settings.get('loyal_min_spent', 5000000)), step=100000, format="%d")
            loyal_pur = st.number_input("Ngưỡng số lần mua - Khách Thân thiết", value=int(settings.get('loyal_min_purchases', 10)), step=1)
            longtime_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) - Khách Lâu năm", value=float(settings.get('longtime_min_spent', 2000000)), step=100000, format="%d")
            longtime_pur = st.number_input("Ngưỡng số lần mua - Khách Lâu năm", value=int(settings.get('longtime_min_purchases', 5)), step=1)
            loyal_disc = st.number_input("Giảm giá (%) - Thân thiết", value=float(settings.get('loyal_discount', 5)), step=0.5)
            longtime_disc = st.number_input("Giảm giá (%) - Lâu năm", value=float(settings.get('longtime_discount', 2)), step=0.5)
            regular_disc = st.number_input("Giảm giá (%) - Thường", value=float(settings.get('regular_discount', 0)), step=0.5)
            if st.form_submit_button("Lưu"):
                with SessionLocal() as session:
                    for k, v in [('loyal_min_spent', loyal_spent), ('loyal_min_purchases', loyal_pur),
                                 ('longtime_min_spent', longtime_spent), ('longtime_min_purchases', longtime_pur),
                                 ('loyal_discount', loyal_disc), ('longtime_discount', longtime_disc),
                                 ('regular_discount', regular_disc)]:
                        setting = session.query(Setting).filter_by(key=k).first()
                        setting.value = str(v)
                    session.commit()
                clear_cache()
                st.success("Đã lưu")
                st.rerun()
        st.subheader("Tải lên danh sách khách hàng (CSV)")
        uploaded = st.file_uploader("File CSV (cột: name, phone, total_spent, total_purchases)", type="csv")
        if uploaded:
            upload_customers_csv(uploaded)
            st.success("Đã cập nhật")

    elif menu == "📦 Sản phẩm":
        st.header("Quản lý sản phẩm")
        tab1, tab2 = st.tabs(["Thêm mới", "Sửa/Xóa"])
        with tab1:
            with st.form("add_prod"):
                name = st.text_input("Tên sản phẩm")
                price = st.number_input("Giá bán", min_value=0.0, step=1000.0, format="%d")
                stock = st.number_input("Số lượng trong kho", min_value=0, step=1)
                barcode = st.text_input("Mã vạch (tùy chọn)")
                image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
                if st.form_submit_button("Thêm"):
                    if name and price > 0:
                        add_product(name, price, stock, image, barcode)
                        st.success("Đã thêm")
                        st.rerun()
        with tab2:
            products = get_all_products_cached()
            if products:
                prod_dict = {f"{p['id']} - {p['name']}": p for p in products}
                selected = st.selectbox("Chọn sản phẩm", list(prod_dict.keys()))
                p = prod_dict[selected]
                with st.form("edit_prod"):
                    new_name = st.text_input("Tên", p['name'])
                    new_price = st.number_input("Giá", value=p['price'], step=1000.0, format="%d")
                    new_stock = st.number_input("Tồn kho", value=p['stock'], step=1)
                    new_barcode = st.text_input("Mã vạch", value=p['barcode'] or "")
                    new_image = st.file_uploader("Thay ảnh mới", type=['png','jpg','jpeg'])
                    if st.form_submit_button("Cập nhật"):
                        update_product(p['id'], new_name, new_price, new_stock, new_image, new_barcode)
                        st.success("Đã cập nhật")
                        st.rerun()
                if st.button("Xóa", key="del"):
                    delete_product(p['id'])
                    st.rerun()
            else:
                st.info("Chưa có sản phẩm")

    elif menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng")
        customers = get_customers_cached()
        if customers:
            df = pd.DataFrame(customers)
            # Hiển thị số nguyên
            df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df)
        else:
            st.info("Chưa có khách hàng")

    elif menu == "🔥 Khách thân thiết":
        st.header("Khách hàng thân thiết")
        loyals = get_loyal_customers_cached()
        if loyals:
            df = pd.DataFrame(loyals)
            df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df)
        else:
            st.info("Chưa có")
        st.subheader("Top 10 VIP")
        vips = get_top_vip_customers_cached(10)
        if vips:
            df_vip = pd.DataFrame(vips)
            df_vip['total_spent'] = df_vip['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df_vip)

    elif menu == "📊 Dashboard":
        st.header("Báo cáo doanh thu")
        sales_data = get_sales_data()
        customers = get_customers_cached()
        if sales_data:
            total_revenue = sum(s['final_amount'] for s in sales_data)
            col1, col2, col3 = st.columns(3)
            col1.metric("Tổng doanh thu", f"{int(total_revenue):,} VNĐ")
            col2.metric("Số đơn hàng", len(sales_data))
            col3.metric("Khách hàng", len(customers))
            df_sales = pd.DataFrame(sales_data)
            df_sales['date'] = pd.to_datetime(df_sales['date']).dt.date
            df_sales = df_sales.groupby('date')['final_amount'].sum().reset_index()
            fig = px.line(df_sales, x='date', y='final_amount', title='Doanh thu theo ngày')
            st.plotly_chart(fig, use_container_width=True)
            top_products = get_top_products_sold()
            if top_products:
                df_top = pd.DataFrame(top_products)
                fig2 = px.bar(df_top, x='name', y='total_qty', title='Top sản phẩm bán chạy')
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Chưa có dữ liệu")

    elif menu == "🏠 Trang chủ":
        st.header("Tổng quan hệ thống")
        st.info("Chào mừng Admin!")

# -------------------- NHÂN VIÊN --------------------
else:
    if menu == "🏠 Trang chủ":
        st.header("Chào mừng nhân viên")
        st.info("Sử dụng menu để bán hàng, xem kho, quản lý khách hàng.")

    elif menu == "📦 Sản phẩm":
        st.header("Thêm sản phẩm mới")
        with st.form("staff_add"):
            name = st.text_input("Tên sản phẩm")
            price = st.number_input("Giá bán", min_value=0.0, step=1000.0, format="%d")
            stock = st.number_input("Số lượng nhập", min_value=0, step=1)
            barcode = st.text_input("Mã vạch (tùy chọn)")
            image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
            if st.form_submit_button("Thêm"):
                if name and price > 0:
                    add_product(name, price, stock, image, barcode)
                    st.success("Đã thêm")
                    st.rerun()
        st.subheader("Danh sách sản phẩm")
        products = get_all_products_cached()
        if products:
            cols = st.columns(4)
            for i, p in enumerate(products):
                with cols[i % 4]:
                    if p['image_url']:
                        st.image(p['image_url'], use_container_width=True)
                    st.markdown(f"<div class='product-card'><h4>{p['name']}</h4><p class='price'>{int(p['price']):,}đ</p><p class='stock'>📦 Tồn: {p['stock']}</p></div>", unsafe_allow_html=True)
        else:
            st.info("Chưa có sản phẩm")

    elif menu == "🛒 Bán hàng":
        st.header("🛒 Bán hàng")
        
        # Bước 1: Chọn khách hàng
        if st.session_state.sale_step == 1:
            customers = get_customers_cached()
            if not customers:
                st.warning("Chưa có khách hàng. Vui lòng thêm mới.")
                with st.form("new_cust"):
                    name = st.text_input("Tên khách hàng")
                    phone = st.text_input("Số điện thoại")
                    if st.form_submit_button("Tạo khách hàng"):
                        if name and phone:
                            add_customer(name, phone)
                            st.rerun()
            else:
                # Hiển thị danh sách khách hàng để chọn
                cust_options = {f"{c['name']} - {c['phone']} ({c['type']})": c['id'] for c in customers}
                selected = st.selectbox("Chọn khách hàng", list(cust_options.keys()))
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Chọn khách hàng này"):
                        st.session_state.current_customer = cust_options[selected]
                        st.session_state.sale_step = 2
                        st.rerun()
                with col2:
                    if st.button("➕ Thêm khách hàng mới"):
                        with st.expander("Nhập thông tin", expanded=True):
                            new_name = st.text_input("Tên mới")
                            new_phone = st.text_input("SĐT mới")
                            if st.button("Thêm và chọn"):
                                if new_name and new_phone:
                                    add_customer(new_name, new_phone)
                                    clear_cache()
                                    customers_new = get_customers_cached()
                                    for c in customers_new:
                                        if c['phone'] == new_phone:
                                            st.session_state.current_customer = c['id']
                                            break
                                    st.session_state.sale_step = 2
                                    st.rerun()
        else:
            # Bước 2: Tạo giỏ hàng và thanh toán
            st.subheader("🧾 Giỏ hàng")
            # Hiển thị giỏ hàng
            if st.session_state.cart:
                # Bảng giỏ hàng
                cart_df = pd.DataFrame(st.session_state.cart)
                cart_df['Thành tiền'] = cart_df['price'] * cart_df['qty']
                st.dataframe(cart_df[['name', 'price', 'qty', 'Thành tiền']].rename(columns={'price':'Đơn giá', 'qty':'SL'}))
                
                total = sum(item['price'] * item['qty'] for item in st.session_state.cart)
                discount_percent = get_discount_for_customer(st.session_state.current_customer)
                discount_amount = total * discount_percent / 100
                final_total = total - discount_amount
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Tổng tiền", f"{int(total):,} VNĐ")
                col2.metric(f"Giảm giá ({discount_percent}%)", f"-{int(discount_amount):,} VNĐ")
                col3.metric("Thực thu", f"{int(final_total):,} VNĐ")
                
                # Nút xóa từng sản phẩm
                st.write("**Xóa sản phẩm:**")
                for idx, item in enumerate(st.session_state.cart):
                    if st.button(f"❌ Xóa {item['name']}", key=f"del_{idx}"):
                        st.session_state.cart.pop(idx)
                        st.rerun()
                
                colA, colB = st.columns(2)
                with colA:
                    if st.button("💰 Thanh toán", use_container_width=True):
                        cart_items = [(item['id'], item['qty'], item['price']) for item in st.session_state.cart]
                        try:
                            sale_id, final_amt, disc_amt = record_sale(st.session_state.current_customer, cart_items, discount_percent)
                            st.success(f"Thanh toán thành công! Hóa đơn #{sale_id}")
                            # Lấy thông tin khách hàng để in PDF
                            customers = get_customers_cached()
                            cust = next((c for c in customers if c['id'] == st.session_state.current_customer), None)
                            if cust:
                                pdf = generate_pdf_invoice(sale_id, cust['name'], cust['phone'], cust['type'],
                                                           st.session_state.cart, total, disc_amt, final_amt)
                                st.download_button("📄 Tải hóa đơn PDF", data=pdf, file_name=f"invoice_{sale_id}.pdf", mime="application/pdf")
                            # Reset giỏ hàng và quay lại bước 1
                            st.session_state.cart = []
                            st.session_state.sale_step = 1
                            st.session_state.current_customer = None
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                with colB:
                    if st.button("🗑 Hủy đơn", use_container_width=True):
                        st.session_state.cart = []
                        st.session_state.sale_step = 1
                        st.session_state.current_customer = None
                        st.rerun()
            else:
                st.info("Giỏ hàng trống. Hãy thêm sản phẩm bên dưới.")
            
            st.markdown("---")
            st.subheader("🛍 Thêm sản phẩm vào giỏ")
            # Tìm kiếm sản phẩm
            search = st.text_input("🔍 Tìm kiếm (tên hoặc mã vạch)", value=st.session_state.search_term)
            if search != st.session_state.search_term:
                st.session_state.search_term = search
                st.rerun()
            products = get_all_products_cached(st.session_state.search_term)
            if products:
                # Hiển thị dạng grid
                cols = st.columns(4)
                for i, p in enumerate(products):
                    with cols[i % 4]:
                        if p['image_url']:
                            st.image(p['image_url'], use_container_width=True)
                        st.markdown(f"<div class='product-card'><h4>{p['name']}</h4><p class='price'>{int(p['price']):,}đ</p><p class='stock'>📦 Tồn: {p['stock']}</p></div>", unsafe_allow_html=True)
                        qty = st.number_input("Số lượng", min_value=1, max_value=p['stock'], value=1, key=f"qty_{p['id']}")
                        if st.button("➕ Thêm vào giỏ", key=f"add_{p['id']}"):
                            # Kiểm tra xem đã có trong giỏ chưa
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
                                st.session_state.cart.append({'id': p['id'], 'name': p['name'], 'price': p['price'], 'qty': qty})
                            st.rerun()
            else:
                st.info("Không tìm thấy sản phẩm")
    
    elif menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng")
        customers = get_customers_cached()
        if customers:
            df = pd.DataFrame(customers)
            df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df)
        else:
            st.info("Chưa có khách hàng")

    elif menu == "🔥 Khách thân thiết":
        st.header("Khách hàng thân thiết")
        loyals = get_loyal_customers_cached()
        if loyals:
            df = pd.DataFrame(loyals)
            df['total_spent'] = df['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df)
        else:
            st.info("Chưa có")
        st.subheader("Top 10 VIP")
        vips = get_top_vip_customers_cached(10)
        if vips:
            df_vip = pd.DataFrame(vips)
            df_vip['total_spent'] = df_vip['total_spent'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df_vip)

    elif menu == "📊 Báo cáo":
        st.header("Lịch sử bán hàng")
        sales_data = get_sales_data()
        if sales_data:
            df = pd.DataFrame(sales_data)
            df['final_amount'] = df['final_amount'].apply(lambda x: f"{int(x):,}")
            st.dataframe(df)
        else:
            st.info("Chưa có hóa đơn")

# Đăng xuất
if st.sidebar.button("Đăng xuất"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

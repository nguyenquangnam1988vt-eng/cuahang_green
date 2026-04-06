import streamlit as st
import pandas as pd
import os
import bcrypt
from datetime import datetime, date
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text, or_, func, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
import cloudinary
import cloudinary.uploader
import plotly.express as px
from fpdf import FPDF
import io
from dotenv import load_dotenv
from typing import List, Dict, Optional

# ---------- CẤU HÌNH STREAMLIT ----------
st.set_page_config(page_title="Hệ thống bán hàng Pro", layout="wide")

# ---------- LOAD BIẾN MÔI TRƯỜNG ----------
if os.environ.get('STREAMLIT_CLOUD') or os.environ.get('STREAMLIT_RUNTIME'):
    try:
        DATABASE_URL = st.secrets["DATABASE_URL"]
        CLOUD_NAME = st.secrets["CLOUD_NAME"]
        API_KEY = st.secrets["API_KEY"]
        API_SECRET = st.secrets["API_SECRET"]
    except:
        st.error("❌ Thiếu secrets trên Streamlit Cloud. Vui lòng cấu hình trong 'Secrets'.")
        st.stop()
else:
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    CLOUD_NAME = os.getenv("CLOUD_NAME")
    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    if not all([DATABASE_URL, CLOUD_NAME, API_KEY, API_SECRET]):
        st.error("❌ Bạn chưa set DATABASE_URL hoặc Cloudinary API trong file .env")
        st.stop()

# ---------- CẤU HÌNH CLOUDINARY (CACHE) ----------
@st.cache_resource
def init_cloudinary():
    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=API_KEY,
        api_secret=API_SECRET
    )
    return True

init_cloudinary()

# ---------- CẤU HÌNH DATABASE (CACHE) ----------
@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, echo=False, future=True)

@st.cache_resource
def get_session_local():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)

engine = get_engine()
SessionLocal = get_session_local()

# ---------- MODELS ----------
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    cost = Column(Float, default=0.0)
    stock = Column(Integer, nullable=False)
    image_url = Column(String)
    barcode = Column(String, unique=True, nullable=True)

class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer)
    price = Column(Float)
    transaction_date = Column(DateTime, default=datetime.now)
    note = Column(String, nullable=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True)
    total_spent = Column(Float, default=0)
    total_purchases = Column(Integer, default=0)
    debt = Column(Float, default=0.0)
    type = Column(String, default='regular')

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    amount = Column(Float)
    payment_date = Column(DateTime, default=datetime.now)
    note = Column(String, nullable=True)

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    date = Column(DateTime, default=datetime.now)
    total_amount = Column(Float)
    discount = Column(Float)
    final_amount = Column(Float)
    paid_amount = Column(Float, default=0.0)
    debt_after = Column(Float, default=0.0)
    customer = relationship("Customer")

class SaleItem(Base):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer)
    price = Column(Float)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)

# ---------- KIỂM TRA VÀ TẠO BẢNG (XỬ LÝ LỖI) ----------
def create_tables_safe():
    """Tạo bảng nếu chưa có, bắt lỗi và retry nếu cần."""
    try:
        Base.metadata.create_all(engine)
        # Kiểm tra xem bảng products có tồn tại không
        inspector = inspect(engine)
        if 'products' not in inspector.get_table_names():
            raise Exception("Bảng products chưa được tạo")
    except Exception as e:
        st.error(f"Lỗi khi tạo bảng: {e}. Thử lại...")
        # Xóa cache engine và thử lại
        st.cache_resource.clear()
        time.sleep(1)
        Base.metadata.create_all(engine)

# Gọi tạo bảng ngay khi khởi động
create_tables_safe()

# Kiểm tra và thêm cột debt nếu cần (cho database cũ)
def ensure_schema_up_to_date():
    try:
        inspector = inspect(engine)
        if 'customers' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('customers')]
            if 'debt' not in columns:
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE customers ADD COLUMN debt FLOAT DEFAULT 0.0"))
                    conn.commit()
                    st.info("Đã thêm cột debt vào bảng customers (nâng cấp database).")
    except Exception as e:
        st.warning(f"Không thể cập nhật schema (có thể do quyền): {e}")

ensure_schema_up_to_date()

# ---------- HÀM TIỆN ÍCH ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def init_data():
    with SessionLocal() as session:
        try:
            if not session.query(User).filter_by(username="admin").first():
                admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
                staff = User(username="staff", password_hash=hash_password("staff123"), role="staff")
                session.add_all([admin, staff])
            defaults = {
                "loyal_min_spent": "5000000", "loyal_min_purchases": "10",
                "longtime_min_spent": "2000000", "longtime_min_purchases": "5",
                "loyal_discount": "5", "longtime_discount": "2", "regular_discount": "0"
            }
            for k, v in defaults.items():
                if not session.query(Setting).filter_by(key=k).first():
                    session.add(Setting(key=k, value=v))
            session.commit()
        except ProgrammingError as e:
            st.error(f"Lỗi database khi khởi tạo dữ liệu: {e}. Hãy kiểm tra kết nối và schema.")
            st.stop()

init_data()

def upload_image_to_cloudinary(image_file):
    if image_file is None:
        return ""
    try:
        result = cloudinary.uploader.upload(image_file, folder="sales_app",
                                            transformation=[{"width": 500, "height": 500, "crop": "limit"}])
        return result.get("secure_url", "")
    except Exception as e:
        st.error(f"Lỗi upload ảnh: {e}")
        return ""

# ---------- QUẢN LÝ SẢN PHẨM ----------
def add_product(name: str, price: float, cost: float, stock: int, image_file=None, barcode=None):
    with SessionLocal() as session:
        image_url = upload_image_to_cloudinary(image_file) if image_file else ""
        product = Product(name=name, price=price, cost=cost, stock=stock, image_url=image_url, barcode=barcode)
        session.add(product)
        session.flush()
        if stock > 0:
            trans = InventoryTransaction(product_id=product.id, quantity=stock, price=cost, note="Nhập kho lần đầu")
            session.add(trans)
        session.commit()

def update_product(product_id: int, name: str, price: float, cost: float, stock: int, image_file=None, barcode=None):
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if not product:
            return
        diff = stock - product.stock
        if diff != 0:
            note = "Nhập kho (điều chỉnh)" if diff > 0 else "Xuất kho (điều chỉnh)"
            trans = InventoryTransaction(product_id=product_id, quantity=diff, price=cost if diff>0 else product.price, note=note)
            session.add(trans)
        product.name = name
        product.price = price
        product.cost = cost
        product.stock = stock
        if image_file:
            product.image_url = upload_image_to_cloudinary(image_file)
        if barcode:
            product.barcode = barcode
        session.commit()

def delete_product(product_id: int):
    with SessionLocal() as session:
        session.query(Product).filter_by(id=product_id).delete()
        session.commit()

def import_stock(product_id: int, quantity: int, import_price: float, note: str = "Nhập kho"):
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if not product:
            return False
        total_value = product.stock * product.cost
        new_total_value = total_value + (quantity * import_price)
        new_stock = product.stock + quantity
        new_avg_cost = new_total_value / new_stock if new_stock > 0 else 0
        product.stock = new_stock
        product.cost = new_avg_cost
        trans = InventoryTransaction(product_id=product_id, quantity=quantity, price=import_price, note=note)
        session.add(trans)
        session.commit()
        return True

# ---------- QUẢN LÝ KHÁCH HÀNG & CÔNG NỢ ----------
def add_customer(name: str, phone: str):
    with SessionLocal() as session:
        cust = Customer(name=name, phone=phone)
        session.add(cust)
        session.commit()

def get_customers():
    with SessionLocal() as session:
        return session.query(Customer).all()

def update_customer_type(customer_id: int):
    with SessionLocal() as session:
        cust = session.get(Customer, customer_id)
        if cust:
            loyal_spent = float(session.query(Setting).filter_by(key='loyal_min_spent').first().value)
            loyal_pur = int(session.query(Setting).filter_by(key='loyal_min_purchases').first().value)
            longtime_spent = float(session.query(Setting).filter_by(key='longtime_min_spent').first().value)
            longtime_pur = int(session.query(Setting).filter_by(key='longtime_min_purchases').first().value)
            if cust.total_spent >= loyal_spent and cust.total_purchases >= loyal_pur:
                cust.type = 'loyal'
            elif cust.total_spent >= longtime_spent and cust.total_purchases >= longtime_pur:
                cust.type = 'longtime'
            else:
                cust.type = 'regular'
            session.commit()

def get_discount_for_customer(customer_id: Optional[int]) -> float:
    if not customer_id:
        return 0
    with SessionLocal() as session:
        cust = session.get(Customer, customer_id)
        if not cust:
            return 0
        key = f"{cust.type}_discount"
        disc = float(session.query(Setting).filter_by(key=key).first().value)
        return disc

def add_payment(customer_id: int, amount: float, note: str = "Khách trả nợ"):
    with SessionLocal() as session:
        cust = session.get(Customer, customer_id)
        if cust and amount > 0 and cust.debt >= amount:
            cust.debt -= amount
            payment = Payment(customer_id=customer_id, amount=amount, note=note)
            session.add(payment)
            session.commit()
            return True
    return False

def get_payment_history(customer_id: int):
    with SessionLocal() as session:
        return session.query(Payment).filter_by(customer_id=customer_id).order_by(Payment.payment_date).all()

# ---------- BÁN HÀNG ----------
def record_sale(customer_id: int, cart_items: List[Dict], discount_percent: float, paid_amount: float = 0):
    with SessionLocal() as session:
        for item in cart_items:
            product = session.get(Product, item['product_id'])
            if not product or product.stock < item['quantity']:
                raise ValueError(f"Sản phẩm {product.name if product else '?'} không đủ hàng")
        total = sum(item['price'] * item['quantity'] for item in cart_items)
        discount_amount = total * discount_percent / 100
        final = total - discount_amount
        debt = max(0, final - paid_amount)
        cust = session.get(Customer, customer_id)
        old_debt = cust.debt if cust else 0
        new_debt = old_debt + debt
        sale = Sale(customer_id=customer_id, total_amount=total, discount=discount_amount,
                    final_amount=final, paid_amount=paid_amount, debt_after=new_debt)
        session.add(sale)
        session.flush()
        for item in cart_items:
            product = session.get(Product, item['product_id'])
            product.stock -= item['quantity']
            sale_item = SaleItem(sale_id=sale.id, product_id=item['product_id'],
                                 quantity=item['quantity'], price=item['price'])
            session.add(sale_item)
            trans = InventoryTransaction(product_id=item['product_id'], quantity=-item['quantity'],
                                         price=item['price'], note=f"Bán hàng - HĐ {sale.id}", sale_id=sale.id)
            session.add(trans)
        if cust:
            cust.total_spent += final
            cust.total_purchases += 1
            cust.debt = new_debt
        session.commit()
        update_customer_type(customer_id)
        return sale.id, final, new_debt

# ---------- CÁC HÀM LẤY DỮ LIỆU CÓ CACHE (CÓ XỬ LÝ LỖI PROGRAMMINGERROR) ----------
def safe_query(query_func, *args, **kwargs):
    """Thực thi query, nếu gặp ProgrammingError thì clear cache và thử lại."""
    try:
        return query_func(*args, **kwargs)
    except ProgrammingError as e:
        st.warning(f"Lỗi schema database: {e}. Đang xóa cache và thử lại...")
        clear_cache()
        # Tạo lại bảng nếu cần
        create_tables_safe()
        return query_func(*args, **kwargs)

@st.cache_data(ttl=30)
def get_all_products_cached(search_term=""):
    with SessionLocal() as session:
        query = session.query(Product)
        if search_term:
            query = query.filter(
                or_(
                    Product.name.contains(search_term),
                    Product.barcode.isnot(None) & Product.barcode.contains(search_term)
                )
            )
        return query.all()

@st.cache_data(ttl=60)
def get_customers_cached():
    with SessionLocal() as session:
        return session.query(Customer).all()

@st.cache_data(ttl=60)
def get_settings_cached():
    with SessionLocal() as session:
        return {s.key: s.value for s in session.query(Setting).all()}

@st.cache_data(ttl=120)
def get_sales_report(start_date=None, end_date=None):
    with SessionLocal() as session:
        query = session.query(Sale)
        if start_date:
            query = query.filter(func.date(Sale.date) >= start_date)
        if end_date:
            query = query.filter(func.date(Sale.date) <= end_date)
        return query.all()

@st.cache_data(ttl=120)
def get_inventory_transactions(product_id=None):
    with SessionLocal() as session:
        q = session.query(InventoryTransaction).order_by(InventoryTransaction.transaction_date)
        if product_id:
            q = q.filter(InventoryTransaction.product_id == product_id)
        return q.all()

def clear_cache():
    st.cache_data.clear()

# ---------- HÀM TẠO PDF ----------
def generate_pdf_invoice(sale_id, customer_name, customer_phone, customer_type, items, total, discount, final, paid, debt):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, "HÓA ĐƠN BÁN HÀNG", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, f"Mã HD: {sale_id}", ln=True)
    pdf.cell(200, 10, f"Khách hàng: {customer_name} - {customer_phone} ({customer_type})", ln=True)
    pdf.cell(200, 10, f"Ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.ln(10)
    pdf.cell(80, 10, "Sản phẩm", 1)
    pdf.cell(30, 10, "SL", 1)
    pdf.cell(40, 10, "Đơn giá", 1)
    pdf.cell(40, 10, "Thành tiền", 1)
    pdf.ln()
    for item in items:
        pdf.cell(80, 10, item['name'], 1)
        pdf.cell(30, 10, str(item['quantity']), 1)
        pdf.cell(40, 10, f"{item['price']:,.0f}", 1)
        pdf.cell(40, 10, f"{item['price']*item['quantity']:,.0f}", 1)
        pdf.ln()
    pdf.ln(5)
    pdf.cell(200, 10, f"Tổng tiền: {total:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, f"Giảm giá: {discount:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, f"Thực thu: {final:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, f"Khách đã trả: {paid:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, f"Công nợ sau hóa đơn: {debt:,.0f} VNĐ", ln=True)
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
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.cart = []
    st.session_state.sale_step = 1
    st.session_state.current_customer_id = None

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

menu_options = ["🏠 Trang chủ", "📦 Quản lý sản phẩm", "🛒 Bán hàng", "👥 Khách hàng & Công nợ", "📊 Báo cáo", "⚙️ Cài đặt (Admin)"]
menu = st.sidebar.radio("Chức năng", menu_options)

# -------------------- TRANG CHỦ --------------------
if menu == "🏠 Trang chủ":
    st.title("Dashboard tổng quan")
    with SessionLocal() as session:
        total_revenue = session.query(func.sum(Sale.final_amount)).scalar()
        total_revenue = total_revenue if total_revenue is not None else 0.0
        
        total_customers = session.query(func.count(Customer.id)).scalar()
        total_customers = total_customers if total_customers is not None else 0
        
        total_products = session.query(func.count(Product.id)).scalar()
        total_products = total_products if total_products is not None else 0
        
        total_debt = session.query(func.sum(Customer.debt)).scalar()
        total_debt = total_debt if total_debt is not None else 0.0
        
        today = date.today()
        revenue_today = session.query(func.sum(Sale.final_amount)).filter(func.date(Sale.date) == today).scalar()
        revenue_today = revenue_today if revenue_today is not None else 0.0
        
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tổng doanh thu", f"{total_revenue:,.0f} VNĐ")
    col2.metric("Sản phẩm", total_products)
    col3.metric("Khách hàng", total_customers)
    col4.metric("Tổng công nợ", f"{total_debt:,.0f} VNĐ")
    st.metric("Doanh thu hôm nay", f"{revenue_today:,.0f} VNĐ")
    st.subheader("Top 10 sản phẩm bán chạy")
    with SessionLocal() as session:
        top = session.query(
            Product.name,
            func.sum(SaleItem.quantity).label("sold")
        ).join(SaleItem, Product.id == SaleItem.product_id)\
         .group_by(Product.name)\
         .order_by(func.sum(SaleItem.quantity).desc())\
         .limit(10).all()
    if top:
        df = pd.DataFrame(top, columns=["Sản phẩm", "Số lượng bán"])
        fig = px.bar(df, x="Sản phẩm", y="Số lượng bán", text="Số lượng bán")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu bán hàng")

# -------------------- QUẢN LÝ SẢN PHẨM & NHẬP KHO --------------------
elif menu == "📦 Quản lý sản phẩm":
    st.title("Quản lý sản phẩm & Nhập kho")
    tab1, tab2, tab3 = st.tabs(["Danh sách sản phẩm", "Thêm/Sửa sản phẩm", "Nhập kho"])
    with tab1:
        st.subheader("Danh sách sản phẩm")
        search = st.text_input("Tìm kiếm theo tên hoặc mã vạch", key="search_prod")
        products = safe_query(get_all_products_cached, search)
        if not products:
            st.info("Không có sản phẩm")
        else:
            page_size = 20
            total_pages = (len(products) + page_size - 1) // page_size
            page = st.number_input("Trang", min_value=1, max_value=total_pages, value=1, step=1)
            start = (page-1)*page_size
            end = start + page_size
            for p in products[start:end]:
                cols = st.columns([1,3,1,1,1,1,1])
                cols[0].image(p.image_url or "https://via.placeholder.com/50", width=50)
                cols[1].write(f"**{p.name}**")
                cols[2].write(f"{p.price:,.0f}đ")
                cols[3].write(f"Vốn: {p.cost:,.0f}đ")
                cols[4].write(p.stock)
                cols[5].write(p.barcode or "")
                if cols[6].button("Xóa", key=f"del_{p.id}"):
                    delete_product(p.id)
                    clear_cache()
                    st.rerun()
    with tab2:
        st.subheader("Thêm / Cập nhật sản phẩm")
        with st.form("product_form"):
            products_list = safe_query(get_all_products_cached)
            product_options = ["-- Thêm mới --"] + [f"{p.id} - {p.name}" for p in products_list]
            selected = st.selectbox("Chọn sản phẩm để sửa", product_options)
            name = st.text_input("Tên sản phẩm")
            price = st.number_input("Giá bán (VNĐ)", min_value=0.0, step=1000.0)
            cost = st.number_input("Giá nhập (VNĐ)", min_value=0.0, step=1000.0)
            stock = st.number_input("Số lượng tồn", min_value=0, step=1)
            barcode = st.text_input("Mã vạch")
            image_file = st.file_uploader("Hình ảnh", type=["png","jpg","jpeg"])
            submitted = st.form_submit_button("Lưu")
            if submitted:
                try:
                    if selected == "-- Thêm mới --":
                        if name and price>0:
                            add_product(name, price, cost, stock, image_file, barcode)
                            st.success("Thêm sản phẩm thành công")
                    else:
                        prod_id = int(selected.split(" - ")[0])
                        update_product(prod_id, name, price, cost, stock, image_file, barcode)
                        st.success("Cập nhật thành công")
                    clear_cache()
                    st.rerun()
                except IntegrityError:
                    st.error("Mã vạch đã tồn tại!")
    with tab3:
        st.subheader("Nhập kho (tăng số lượng, cập nhật giá vốn bình quân)")
        products = safe_query(get_all_products_cached)
        if not products:
            st.warning("Chưa có sản phẩm nào")
        else:
            prod_dict = {f"{p.id} - {p.name} (tồn: {p.stock}, giá vốn: {p.cost:,.0f})": p for p in products}
            selected_prod = st.selectbox("Chọn sản phẩm", list(prod_dict.keys()))
            prod = prod_dict[selected_prod]
            qty_import = st.number_input("Số lượng nhập", min_value=1, step=1, value=1)
            import_price = st.number_input("Giá nhập (VNĐ)", min_value=0.0, value=prod.cost, step=1000.0)
            note = st.text_input("Ghi chú (tùy chọn)", value="Nhập kho")
            if st.button("Xác nhận nhập kho"):
                if import_stock(prod.id, qty_import, import_price, note):
                    clear_cache()
                    st.success(f"Đã nhập {qty_import} sản phẩm {prod.name} với giá {import_price:,.0f}đ, giá vốn mới: {prod.cost:,.0f}đ")
                    st.rerun()
                else:
                    st.error("Lỗi khi nhập kho")

# -------------------- BÁN HÀNG --------------------
elif menu == "🛒 Bán hàng":
    st.title("Bán hàng")
    customers = safe_query(get_customers_cached)
    cust_options = {f"{c.name} - {c.phone} (nợ: {c.debt:,.0f}đ)": c.id for c in customers}
    cust_options["Khách lẻ (không lưu)"] = None
    selected_cust_label = st.selectbox("Chọn khách hàng", list(cust_options.keys()))
    customer_id = cust_options[selected_cust_label]
    if customer_id:
        cust_info = next((c for c in customers if c.id == customer_id), None)
        if cust_info and cust_info.debt > 0:
            st.warning(f"Khách hàng đang nợ {cust_info.debt:,.0f} VNĐ. Có thể thanh toán nợ ở mục Khách hàng.")
    else:
        customer_id = None

    st.subheader("Giỏ hàng")
    if st.session_state.cart:
        df_cart = pd.DataFrame(st.session_state.cart)
        df_cart["Thành tiền"] = df_cart["price"] * df_cart["quantity"]
        st.dataframe(df_cart[["name", "quantity", "price", "Thành tiền"]])
        total = sum(item['price']*item['quantity'] for item in st.session_state.cart)
        discount = get_discount_for_customer(customer_id)
        disc_amount = total * discount / 100
        final = total - disc_amount
        col1, col2, col3 = st.columns(3)
        col1.metric("Tổng tiền", f"{total:,.0f} VNĐ")
        col2.metric(f"Giảm giá ({discount}%)", f"-{disc_amount:,.0f} VNĐ")
        col3.metric("Thực thu", f"{final:,.0f} VNĐ")
        paid = st.number_input("Tiền khách đưa", min_value=0.0, value=final, step=10000.0)
        debt = final - paid
        if debt > 0:
            st.warning(f"Khách còn nợ {debt:,.0f} VNĐ")
        elif debt < 0:
            st.info(f"Thối lại {abs(debt):,.0f} VNĐ")
        colA, colB = st.columns(2)
        with colA:
            if st.button("Thanh toán", use_container_width=True):
                if not customer_id:
                    add_customer("Khách lẻ", "")
                    clear_cache()
                    customers = safe_query(get_customers_cached)
                    customer_id = customers[-1].id if customers else None
                if customer_id:
                    try:
                        sale_id, final_amt, debt_after = record_sale(customer_id, st.session_state.cart, discount, paid)
                        cust_name = next((c.name for c in customers if c.id==customer_id), "Khách lẻ")
                        cust_phone = next((c.phone for c in customers if c.id==customer_id), "")
                        cust_type = next((c.type for c in customers if c.id==customer_id), "regular")
                        pdf_file = generate_pdf_invoice(sale_id, cust_name, cust_phone, cust_type,
                                                         st.session_state.cart, total, disc_amount, final_amt, paid, debt_after)
                        st.download_button("📥 Tải hóa đơn PDF", pdf_file, file_name=f"invoice_{sale_id}.pdf", mime="application/pdf")
                        st.success("Thanh toán thành công!")
                        st.session_state.cart = []
                        clear_cache()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")
                else:
                    st.error("Không thể tạo khách hàng")
        with colB:
            if st.button("Hủy giỏ hàng"):
                st.session_state.cart = []
                st.rerun()
    else:
        st.info("Giỏ hàng trống")
    st.subheader("Thêm sản phẩm")
    search = st.text_input("Tìm kiếm (tên/mã vạch)", key="search_sale")
    products = safe_query(get_all_products_cached, search)
    products_display = products[:20]
    cols = st.columns(4)
    for idx, p in enumerate(products_display):
        with cols[idx % 4]:
            if p.image_url:
                st.image(p.image_url, width=100)
            st.markdown(f"**{p.name}**")
            st.write(f"💰 {p.price:,.0f}đ")
            st.write(f"📦 Tồn: {p.stock}")
            qty = st.number_input("SL", min_value=1, max_value=p.stock, value=1, key=f"qty_{p.id}", label_visibility="collapsed")
            if st.button(f"➕ Thêm", key=f"add_{p.id}"):
                found = False
                for item in st.session_state.cart:
                    if item['product_id'] == p.id:
                        new_qty = item['quantity'] + qty
                        if new_qty <= p.stock:
                            item['quantity'] = new_qty
                        else:
                            st.warning("Vượt quá tồn kho")
                        found = True
                        break
                if not found:
                    st.session_state.cart.append({
                        "product_id": p.id,
                        "name": p.name,
                        "price": p.price,
                        "quantity": qty
                    })
                st.rerun()

# -------------------- KHÁCH HÀNG & CÔNG NỢ --------------------
elif menu == "👥 Khách hàng & Công nợ":
    st.title("Quản lý khách hàng và công nợ")
    tab1, tab2, tab3 = st.tabs(["Danh sách khách hàng", "Thanh toán công nợ", "Lịch sử thanh toán"])
    with tab1:
        customers = safe_query(get_customers_cached)
        if customers:
            df_cust = pd.DataFrame([{
                "ID": c.id,
                "Tên": c.name,
                "SĐT": c.phone,
                "Tổng chi": f"{c.total_spent:,.0f}",
                "Số lần mua": c.total_purchases,
                "Loại": c.type,
                "Công nợ": f"{c.debt:,.0f}"
            } for c in customers])
            st.dataframe(df_cust, use_container_width=True)
        else:
            st.info("Chưa có khách hàng")
        with st.expander("Thêm khách hàng mới"):
            with st.form("new_cust"):
                name = st.text_input("Tên")
                phone = st.text_input("Số điện thoại")
                if st.form_submit_button("Thêm"):
                    add_customer(name, phone)
                    clear_cache()
                    st.success("Đã thêm")
                    st.rerun()
    with tab2:
        st.subheader("Thanh toán công nợ")
        customers = safe_query(get_customers_cached)
        if customers:
            cust_with_debt = [c for c in customers if c.debt > 0]
            if not cust_with_debt:
                st.info("Không có khách hàng nào đang nợ")
            else:
                selected_cust = st.selectbox("Chọn khách hàng", cust_with_debt, format_func=lambda x: f"{x.name} - nợ {x.debt:,.0f}đ")
                pay_amount = st.number_input("Số tiền thanh toán", min_value=0.0, max_value=float(selected_cust.debt), value=float(selected_cust.debt), step=10000.0)
                note = st.text_input("Ghi chú (tùy chọn)", value="Thanh toán nợ")
                if st.button("Xác nhận thanh toán"):
                    if add_payment(selected_cust.id, pay_amount, note):
                        clear_cache()
                        st.success(f"Đã thanh toán {pay_amount:,.0f}đ cho khách {selected_cust.name}")
                        st.rerun()
                    else:
                        st.error("Lỗi: số tiền vượt quá công nợ hoặc khách không tồn tại")
    with tab3:
        st.subheader("Lịch sử thanh toán của khách hàng")
        customers = safe_query(get_customers_cached)
        if customers:
            selected_cust = st.selectbox("Chọn khách hàng", customers, format_func=lambda x: f"{x.name} - {x.phone}")
            payments = get_payment_history(selected_cust.id)
            if payments:
                df_pay = pd.DataFrame([(p.payment_date, p.amount, p.note) for p in payments], columns=["Ngày", "Số tiền", "Ghi chú"])
                st.dataframe(df_pay)
            else:
                st.info("Chưa có giao dịch thanh toán nào")
        else:
            st.info("Chưa có khách hàng")

# -------------------- BÁO CÁO --------------------
elif menu == "📊 Báo cáo":
    st.title("Báo cáo doanh thu & công nợ")
    report_type = st.radio("Chọn loại báo cáo", ["Doanh thu theo ngày", "Doanh thu theo khách hàng", "Lịch sử nhập/xuất kho", "Công nợ khách hàng"])
    if report_type == "Doanh thu theo ngày":
        start = st.date_input("Từ ngày", value=date.today().replace(day=1))
        end = st.date_input("Đến ngày", value=date.today())
        sales = safe_query(get_sales_report, start, end)
        if sales:
            df = pd.DataFrame([(s.date.date(), s.final_amount) for s in sales], columns=["Ngày", "Doanh thu"])
            df = df.groupby("Ngày").sum().reset_index()
            fig = px.line(df, x="Ngày", y="Doanh thu", markers=True, title="Doanh thu theo ngày")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df)
        else:
            st.info("Không có dữ liệu")
    elif report_type == "Doanh thu theo khách hàng":
        with SessionLocal() as session:
            data = session.query(Customer.name, func.sum(Sale.final_amount)).join(Sale, Customer.id == Sale.customer_id).group_by(Customer.name).all()
        if data:
            df = pd.DataFrame(data, columns=["Khách hàng", "Doanh thu"])
            fig = px.bar(df, x="Khách hàng", y="Doanh thu", text="Doanh thu")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chưa có dữ liệu")
    elif report_type == "Lịch sử nhập/xuất kho":
        prod_id = st.selectbox("Chọn sản phẩm (tất cả)", options=[None] + [p.id for p in safe_query(get_all_products_cached)], format_func=lambda x: "Tất cả" if x is None else next((p.name for p in safe_query(get_all_products_cached) if p.id==x), ""))
        transactions = safe_query(get_inventory_transactions, prod_id)
        if transactions:
            df = pd.DataFrame([(t.transaction_date, t.product_id, t.quantity, t.price, t.note) for t in transactions],
                              columns=["Ngày", "Mã SP", "SL", "Giá", "Ghi chú"])
            st.dataframe(df)
        else:
            st.info("Chưa có giao dịch")
    else:
        customers = safe_query(get_customers_cached)
        if customers:
            df_debt = pd.DataFrame([(c.name, c.phone, c.debt) for c in customers if c.debt > 0], columns=["Tên", "SĐT", "Công nợ"])
            st.dataframe(df_debt)
        else:
            st.info("Không có khách nợ")

# -------------------- CÀI ĐẶT ADMIN --------------------
elif menu == "⚙️ Cài đặt (Admin)":
    if st.session_state.role != "admin":
        st.warning("Chỉ admin mới có quyền")
    else:
        st.title("Cài đặt hệ thống")
        settings = safe_query(get_settings_cached)
        key_labels = {
            "loyal_min_spent": "Chi tiêu tối thiểu (VNĐ) - Thân thiết",
            "loyal_min_purchases": "Số lần mua tối thiểu - Thân thiết",
            "longtime_min_spent": "Chi tiêu tối thiểu (VNĐ) - Lâu năm",
            "longtime_min_purchases": "Số lần mua tối thiểu - Lâu năm",
            "loyal_discount": "Giảm giá (%) - Thân thiết",
            "longtime_discount": "Giảm giá (%) - Lâu năm",
            "regular_discount": "Giảm giá (%) - Thường"
        }
        with st.form("settings_form"):
            for key, label in key_labels.items():
                val = st.text_input(label, value=settings.get(key, ""))
                st.session_state[f"set_{key}"] = val
            if st.form_submit_button("Lưu cài đặt"):
                with SessionLocal() as session:
                    for key, label in key_labels.items():
                        setting = session.query(Setting).filter_by(key=key).first()
                        if setting:
                            setting.value = st.session_state[f"set_{key}"]
                    session.commit()
                clear_cache()
                st.success("Đã lưu cài đặt")
                st.rerun()

# Đăng xuất
if st.sidebar.button("Đăng xuất"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# app.py
import streamlit as st
import pandas as pd
import os
import bcrypt
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text, or_, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.exc import IntegrityError
import cloudinary
import cloudinary.uploader
import plotly.express as px
from fpdf import FPDF
import io
from dotenv import load_dotenv

# ---------- LOAD BIẾN MÔI TRƯỜNG ----------
load_dotenv()  # đọc biến từ file .env
DATABASE_URL = os.getenv("DATABASE_URL")
CLOUD_NAME = os.getenv("CLOUD_NAME")
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

if not all([DATABASE_URL, CLOUD_NAME, API_KEY, API_SECRET]):
    st.error("❌ Bạn chưa set DATABASE_URL hoặc Cloudinary API KEY/SECRET")
    st.stop()

cloudinary.config(cloud_name=CLOUD_NAME, api_key=API_KEY, api_secret=API_SECRET)

# ---------- KHỞI TẠO DATABASE ----------
Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# ---------- MODELS ----------
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
    stock = Column(Integer, nullable=False)
    image_url = Column(String)
    barcode = Column(String, unique=True, nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True)
    total_spent = Column(Float, default=0)
    total_purchases = Column(Integer, default=0)
    type = Column(String, default='regular')

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    date = Column(DateTime, default=datetime.now)
    total_amount = Column(Float)
    discount = Column(Float)
    final_amount = Column(Float)
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

Base.metadata.create_all(engine)

# ---------- HÀM TIỆN ÍCH ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def init_data():
    with SessionLocal() as session:
        # tạo user admin và staff mặc định
        if not session.query(User).filter_by(username="admin").first():
            admin = User(username="admin", password_hash=hash_password("admin123"), role="admin")
            staff = User(username="staff", password_hash=hash_password("staff123"), role="staff")
            session.add_all([admin, staff])
        # tạo các setting mặc định
        defaults = {
            "loyal_min_spent": "5000000",
            "loyal_min_purchases": "10",
            "longtime_min_spent": "2000000",
            "longtime_min_purchases": "5",
            "loyal_discount": "5",
            "longtime_discount": "2",
            "regular_discount": "0"
        }
        for k, v in defaults.items():
            if not session.query(Setting).filter_by(key=k).first():
                session.add(Setting(key=k, value=v))
        session.commit()

init_data()

def login(username, password):
    with SessionLocal() as session:
        user = session.query(User).filter_by(username=username).first()
        if user and verify_password(password, user.password_hash):
            return user.role
    return None

def upload_image_to_cloudinary(image_file):
    if image_file is None:
        return ""
    result = cloudinary.uploader.upload(image_file, folder="sales_app")
    return result.get("secure_url", "")

def add_product(name, price, stock, image_file=None, barcode=None):
    with SessionLocal() as session:
        image_url = upload_image_to_cloudinary(image_file)
        product = Product(name=name, price=price, stock=stock, image_url=image_url, barcode=barcode)
        session.add(product)
        session.commit()

def update_product(product_id, name, price, stock, image_file=None, barcode=None):
    with SessionLocal() as session:
        product = session.query(Product).filter_by(id=product_id).first()
        if product:
            product.name = name
            product.price = price
            product.stock = stock
            if image_file:
                product.image_url = upload_image_to_cloudinary(image_file)
            if barcode:
                product.barcode = barcode
            session.commit()

def delete_product(product_id):
    with SessionLocal() as session:
        session.query(Product).filter_by(id=product_id).delete()
        session.commit()

def get_all_products(search_term=""):
    with SessionLocal() as session:
        query = session.query(Product)
        if search_term:
            query = query.filter(
                or_(
                    Product.name.contains(search_term),
                    Product.barcode.contains(search_term)
                )
            )
        return query.all()

def add_customer(name, phone):
    with SessionLocal() as session:
        cust = Customer(name=name, phone=phone)
        session.add(cust)
        session.commit()

def get_customers():
    with SessionLocal() as session:
        return session.query(Customer).all()

def update_customer_type(customer_id):
    with SessionLocal() as session:
        cust = session.query(Customer).filter_by(id=customer_id).first()
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

def get_discount_for_customer(customer_id):
    with SessionLocal() as session:
        cust = session.query(Customer).filter_by(id=customer_id).first()
        if not cust:
            return 0
        key = f"{cust.type}_discount"
        discount = float(session.query(Setting).filter_by(key=key).first().value)
        return discount

def record_sale(customer_id, cart_items, discount_percent):
    """
    cart_items: list of dicts [{'product_id':.., 'quantity':.., 'price':..}]
    """
    with SessionLocal() as session:
        total = sum(item['price']*item['quantity'] for item in cart_items)
        discount_amount = total * discount_percent / 100
        final = total - discount_amount
        sale = Sale(customer_id=customer_id, total_amount=total, discount=discount_amount, final_amount=final)
        session.add(sale)
        session.flush()
        for item in cart_items:
            sale_item = SaleItem(sale_id=sale.id, product_id=item['product_id'], quantity=item['quantity'], price=item['price'])
            session.add(sale_item)
            session.query(Product).filter_by(id=item['product_id']).update({Product.stock: Product.stock - item['quantity']})
        cust = session.query(Customer).filter_by(id=customer_id).first()
        cust.total_spent += final
        cust.total_purchases += 1
        session.commit()
        update_customer_type(customer_id)
        return sale.id, final, discount_amount

def generate_pdf_invoice(sale_id, customer_name, customer_phone, customer_type, items, total, discount, final):
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
    pdf.cell(200, 10, txt=f"Tổng tiền: {total:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, txt=f"Giảm giá: {discount:,.0f} VNĐ", ln=True)
    pdf.cell(200, 10, txt=f"Thực thu: {final:,.0f} VNĐ", ln=True)
    pdf_output = io.BytesIO()
    pdf_output.write(pdf.output(dest='S').encode('latin1'))
    pdf_output.seek(0)
    return pdf_output

# ---------- GIAO DIỆN STREAMLIT ----------
st.set_page_config(page_title="POS KiotViet", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.cart = []
    st.session_state.sale_step = 1

# --- Đăng nhập ---
if not st.session_state.logged_in:
    st.title("🔐 Đăng nhập hệ thống")
    with st.form("login_form"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Đăng nhập"):
            role = login(username, password)
            if role:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.experimental_rerun()
            else:
                st.error("Sai tên đăng nhập hoặc mật khẩu")
    st.stop()

# --- Sidebar ---
menu_options = ["🏠 Trang chủ", "📦 Quản lý sản phẩm", "🛒 Bán hàng", "👥 Quản lý khách hàng", "📊 Báo cáo", "⚙️ Cài đặt (Admin)"]
menu_selection = st.sidebar.radio("Chọn chức năng", menu_options)
# ---------- PHẦN 2: GIAO DIỆN KIOTVIET FULL ----------

# --- Trang chủ ---
if menu_selection == "🏠 Trang chủ":
    st.title("🏠 Dashboard hệ thống POS KiotViet")
    with SessionLocal() as session:
        total_sales = session.query(func.sum(Sale.final_amount)).scalar() or 0
        total_customers = session.query(func.count(Customer.id)).scalar() or 0
        total_products = session.query(func.count(Product.id)).scalar() or 0
        sales_today = session.query(func.sum(Sale.final_amount)).filter(
            func.date(Sale.date) == datetime.today().date()
        ).scalar() or 0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tổng doanh thu", f"{total_sales:,.0f} VNĐ")
    col2.metric("Sản phẩm có trong kho", total_products)
    col3.metric("Khách hàng", total_customers)
    col4.metric("Doanh thu hôm nay", f"{sales_today:,.0f} VNĐ")
    
    st.markdown("---")
    st.subheader("Top 10 sản phẩm bán chạy")
    with SessionLocal() as session:
        result = session.query(
            Product.name,
            func.sum(SaleItem.quantity).label("sold_qty")
        ).join(SaleItem, Product.id == SaleItem.product_id)\
         .group_by(Product.name)\
         .order_by(func.sum(SaleItem.quantity).desc())\
         .limit(10).all()
    df_top_products = pd.DataFrame(result, columns=["Tên sản phẩm", "Số lượng bán"])
    if not df_top_products.empty:
        fig = px.bar(df_top_products, x="Tên sản phẩm", y="Số lượng bán", color="Số lượng bán", text="Số lượng bán")
        st.plotly_chart(fig, use_container_width=True)

# --- Quản lý sản phẩm ---
elif menu_selection == "📦 Quản lý sản phẩm":
    st.title("📦 Quản lý sản phẩm")
    st.subheader("Thêm / Cập nhật sản phẩm")
    with st.form("product_form"):
        products_list = get_all_products()
        product_options = ["--Thêm sản phẩm mới--"] + [f"{p.id} - {p.name}" for p in products_list]
        selected = st.selectbox("Chọn sản phẩm", product_options)
        name = st.text_input("Tên sản phẩm")
        price = st.number_input("Giá bán", min_value=0.0, step=1000.0)
        stock = st.number_input("Số lượng tồn", min_value=0, step=1)
        barcode = st.text_input("Mã vạch (Barcode)")
        image_file = st.file_uploader("Hình ảnh sản phẩm", type=["png","jpg","jpeg"])
        if st.form_submit_button("Lưu sản phẩm"):
            try:
                if selected == "--Thêm sản phẩm mới--":
                    add_product(name, price, stock, image_file=image_file, barcode=barcode)
                    st.success("✅ Thêm sản phẩm thành công")
                else:
                    product_id = int(selected.split(" - ")[0])
                    update_product(product_id, name, price, stock, image_file=image_file, barcode=barcode)
                    st.success("✅ Cập nhật sản phẩm thành công")
            except IntegrityError:
                st.error("Mã vạch đã tồn tại!")
    st.markdown("---")
    st.subheader("Danh sách sản phẩm")
    search_term = st.text_input("Tìm kiếm sản phẩm theo tên hoặc barcode")
    products_display = get_all_products(search_term)
    for p in products_display:
        cols = st.columns([1,3,1,1,1,1])
        cols[0].image(p.image_url or "https://via.placeholder.com/50", width=50)
        cols[1].write(f"**{p.name}**")
        cols[2].write(f"{p.price:,.0f} VNĐ")
        cols[3].write(p.stock)
        cols[4].write(p.barcode or "")
        if cols[5].button("Xóa", key=f"del_{p.id}"):
            delete_product(p.id)
            st.experimental_rerun()

# --- Bán hàng ---
elif menu_selection == "🛒 Bán hàng":
    st.title("🛒 Bán hàng")
    # Chọn khách hàng
    customers = get_customers()
    cust_options = ["Khách lẻ"] + [f"{c.id} - {c.name}" for c in customers]
    selected_customer = st.selectbox("Chọn khách hàng", cust_options)
    customer_id = None
    customer_name = "Khách lẻ"
    customer_phone = ""
    customer_type = "regular"
    if selected_customer != "Khách lẻ":
        customer_id = int(selected_customer.split(" - ")[0])
        cust = [c for c in customers if c.id == customer_id][0]
        customer_name = cust.name
        customer_phone = cust.phone
        customer_type = cust.type
    
    # Giỏ hàng
    st.subheader("Thêm sản phẩm vào giỏ hàng")
    products = get_all_products()
    product_dict = {f"{p.id} - {p.name} ({p.stock} tồn)": p for p in products if p.stock>0}
    selected_prod = st.selectbox("Chọn sản phẩm", list(product_dict.keys()))
    quantity = st.number_input("Số lượng", min_value=1, max_value=product_dict[selected_prod].stock)
    if st.button("Thêm vào giỏ hàng"):
        prod_obj = product_dict[selected_prod]
        st.session_state.cart.append({
            "product_id": prod_obj.id,
            "name": prod_obj.name,
            "price": prod_obj.price,
            "quantity": quantity
        })
        st.success(f"✅ Đã thêm {quantity} x {prod_obj.name} vào giỏ hàng")
    
    # Hiển thị giỏ hàng
    if st.session_state.cart:
        st.subheader("Giỏ hàng")
        df_cart = pd.DataFrame(st.session_state.cart)
        st.dataframe(df_cart)
        if st.button("Xóa giỏ hàng"):
            st.session_state.cart = []
        # Tính tổng
        total = sum(item['price']*item['quantity'] for item in st.session_state.cart)
        discount = get_discount_for_customer(customer_id) if customer_id else 0
        final = total - total*discount/100
        st.write(f"Tổng tiền: {total:,.0f} VNĐ")
        st.write(f"Giảm giá ({discount}%): {total*discount/100:,.0f} VNĐ")
        st.write(f"Thực thu: {final:,.0f} VNĐ")
        if st.button("Thanh toán"):
            if not customer_id:
                # Tạo khách hàng tạm
                add_customer("Khách lẻ", "")
                customer_id = get_customers()[-1].id
            sale_id, final_amount, discount_amount = record_sale(customer_id, st.session_state.cart, discount)
            pdf_file = generate_pdf_invoice(sale_id, customer_name, customer_phone, customer_type, st.session_state.cart, total, discount_amount, final_amount)
            st.download_button("📥 Tải hóa đơn PDF", pdf_file, file_name=f"invoice_{sale_id}.pdf", mime="application/pdf")
            st.success("💰 Thanh toán thành công!")
            st.session_state.cart = []

# --- Quản lý khách hàng ---
elif menu_selection == "👥 Quản lý khách hàng":
    st.title("👥 Quản lý khách hàng")
    st.subheader("Thêm khách hàng mới")
    with st.form("customer_form"):
        name = st.text_input("Tên khách hàng")
        phone = st.text_input("Số điện thoại")
        if st.form_submit_button("Thêm khách hàng"):
            add_customer(name, phone)
            st.success("✅ Thêm khách hàng thành công")
    
    st.markdown("---")
    st.subheader("Danh sách khách hàng")
    customers = get_customers()
    df_cust = pd.DataFrame([{
        "Tên": c.name,
        "SĐT": c.phone,
        "Tổng chi": f"{c.total_spent:,.0f}",
        "Số lần mua": c.total_purchases,
        "Loại khách": c.type
    } for c in customers])
    st.dataframe(df_cust)

# --- Báo cáo ---
elif menu_selection == "📊 Báo cáo":
    st.title("📊 Báo cáo doanh thu")
    st.subheader("Doanh thu theo ngày")
    with SessionLocal() as session:
        sales_data = session.query(
            func.date(Sale.date).label("ngay"),
            func.sum(Sale.final_amount).label("doanhthu")
        ).group_by(func.date(Sale.date)).order_by(func.date(Sale.date)).all()
    if sales_data:
        df_sales = pd.DataFrame(sales_data, columns=["Ngày", "Doanh thu"])
        fig = px.line(df_sales, x="Ngày", y="Doanh thu", title="Doanh thu theo ngày", markers=True)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Chưa có dữ liệu bán hàng.")

# --- Cài đặt (Admin) ---
elif menu_selection == "⚙️ Cài đặt (Admin)":
    if st.session_state.role != "admin":
        st.warning("⚠️ Chỉ admin mới có quyền truy cập.")
    else:
        st.title("⚙️ Cài đặt hệ thống")
        with SessionLocal() as session:
            settings = session.query(Setting).all()
            for s in settings:
                val = st.text_input(s.key, value=s.value, key=s.key)
                if st.button(f"Cập nhật {s.key}", key=f"btn_{s.key}"):
                    s.value = val
                    session.commit()
                    st.success(f"✅ Cập nhật {s.key} thành công")
# ---------- PHẦN 3a: DATABASE NÂNG CAO VÀ MODELS MỚI ----------

from sqlalchemy import Boolean

# Bảng Nhà cung cấp
class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)

# Bảng Phiếu nhập kho
class StockEntry(Base):
    __tablename__ = 'stock_entries'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'))
    supplier_id = Column(Integer, ForeignKey('suppliers.id'))
    quantity = Column(Integer, nullable=False)
    price_per_unit = Column(Float, nullable=False)
    date = Column(DateTime, default=datetime.now)
    staff_username = Column(String, ForeignKey('users.username'))
    product = relationship("Product")
    supplier = relationship("Supplier")
    staff = relationship("User")

# Thêm cột cảnh báo tồn kho trong sản phẩm
if not hasattr(Product, 'min_stock_alert'):
    Product.min_stock_alert = Column(Integer, default=5)  # Mức tồn kho cảnh báo mặc định

# Tạo bảng mới
Base.metadata.create_all(engine)

# ---------- HÀM TIỆN ÍCH MỚI ----------
def add_supplier(name, phone="", email="", address=""):
    with SessionLocal() as session:
        supplier = Supplier(name=name, phone=phone, email=email, address=address)
        session.add(supplier)
        session.commit()

def get_suppliers():
    with SessionLocal() as session:
        return session.query(Supplier).all()

def record_stock_entry(product_id, supplier_id, quantity, price_per_unit, staff_username):
    with SessionLocal() as session:
        entry = StockEntry(
            product_id=product_id,
            supplier_id=supplier_id,
            quantity=quantity,
            price_per_unit=price_per_unit,
            staff_username=staff_username
        )
        session.add(entry)
        # Cập nhật tồn kho sản phẩm
        product = session.query(Product).filter_by(id=product_id).first()
        product.stock += quantity
        session.commit()

def get_stock_entries():
    with SessionLocal() as session:
        return session.query(StockEntry).all()

def check_stock_alerts():
    alerts = []
    with SessionLocal() as session:
        products = session.query(Product).all()
        for p in products:
            if p.stock <= (p.min_stock_alert or 5):
                alerts.append({
                    "name": p.name,
                    "stock": p.stock,
                    "min_alert": p.min_stock_alert
                })
    return alerts
# ---------- PHẦN 3b: UI QUẢN LÝ NHÀ CUNG CẤP VÀ NHẬP KHO ----------

import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="POS KiotViet - Nâng cao",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar menu
st.sidebar.title("Quản lý POS")
menu = st.sidebar.radio("Điều hướng", ["Bán hàng", "Sản phẩm", "Nhập kho", "Nhà cung cấp", "Cảnh báo tồn kho"])

# ----- NHÀ CUNG CẤP -----
if menu == "Nhà cung cấp":
    st.header("Quản lý Nhà Cung Cấp")

    # Form thêm nhà cung cấp
    with st.form("add_supplier_form"):
        st.subheader("Thêm nhà cung cấp mới")
        name = st.text_input("Tên nhà cung cấp")
        phone = st.text_input("Số điện thoại")
        email = st.text_input("Email")
        address = st.text_input("Địa chỉ")
        submitted = st.form_submit_button("Thêm nhà cung cấp")
        if submitted:
            if name.strip() == "":
                st.error("Tên nhà cung cấp không được để trống")
            else:
                add_supplier(name, phone, email, address)
                st.success(f"Thêm nhà cung cấp '{name}' thành công!")

    # Danh sách nhà cung cấp
    st.subheader("Danh sách nhà cung cấp")
    suppliers = get_suppliers()
    if suppliers:
        supplier_data = [{"ID": s.id, "Tên": s.name, "Điện thoại": s.phone, "Email": s.email, "Địa chỉ": s.address} for s in suppliers]
        st.table(supplier_data)
    else:
        st.info("Chưa có nhà cung cấp nào")

# ----- NHẬP KHO -----
if menu == "Nhập kho":
    st.header("Nhập kho sản phẩm")

    products = get_products()
    suppliers = get_suppliers()

    if not products or not suppliers:
        st.warning("Vui lòng đảm bảo đã có sản phẩm và nhà cung cấp trước khi nhập kho")
    else:
        with st.form("stock_entry_form"):
            st.subheader("Phiếu nhập kho")
            product_choice = st.selectbox("Chọn sản phẩm", [(p.id, p.name) for p in products], format_func=lambda x: x[1])
            supplier_choice = st.selectbox("Chọn nhà cung cấp", [(s.id, s.name) for s in suppliers], format_func=lambda x: x[1])
            quantity = st.number_input("Số lượng nhập", min_value=1, step=1)
            price_per_unit = st.number_input("Giá nhập/1 đơn vị", min_value=0.0, step=100.0)
            staff_username = st.text_input("Nhân viên thực hiện", value="admin")
            submitted = st.form_submit_button("Nhập kho")
            if submitted:
                record_stock_entry(
                    product_id=product_choice[0],
                    supplier_id=supplier_choice[0],
                    quantity=quantity,
                    price_per_unit=price_per_unit,
                    staff_username=staff_username
                )
                st.success(f"Nhập kho sản phẩm '{product_choice[1]}' từ nhà cung cấp '{supplier_choice[1]}' thành công!")

    # Hiển thị phiếu nhập kho
    st.subheader("Danh sách phiếu nhập kho gần đây")
    entries = get_stock_entries()
    if entries:
        entry_data = []
        for e in entries[-10:][::-1]:  # 10 phiếu gần nhất
            entry_data.append({
                "ID": e.id,
                "Sản phẩm": e.product.name,
                "Nhà cung cấp": e.supplier.name,
                "Số lượng": e.quantity,
                "Giá/Đơn vị": e.price_per_unit,
                "Nhân viên": e.staff_username,
                "Ngày nhập": e.date.strftime("%d-%m-%Y %H:%M")
            })
        st.table(entry_data)
    else:
        st.info("Chưa có phiếu nhập kho nào")

# ----- CẢNH BÁO TỒN KHO -----
if menu == "Cảnh báo tồn kho":
    st.header("Cảnh báo tồn kho")
    alerts = check_stock_alerts()
    if alerts:
        st.warning("Những sản phẩm dưới mức tồn kho cảnh báo:")
        alert_data = [{"Sản phẩm": a["name"], "Tồn kho hiện tại": a["stock"], "Mức cảnh báo": a["min_alert"]} for a in alerts]
        st.table(alert_data)
    else:
        st.success("Tất cả sản phẩm đều đủ tồn kho")
# ---------- PHẦN 3c: UI NÂNG CAO POS KIOTVIET ----------
import streamlit as st
from datetime import datetime
import pandas as pd

st.set_page_config(
    page_title="POS KiotViet - Full",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar menu chính
st.sidebar.title("POS KiotViet - Dashboard")
menu = st.sidebar.radio("Điều hướng chính", [
    "Bán hàng", "Sản phẩm", "Nhập kho", "Nhà cung cấp", "Khách hàng", "Báo cáo", "Cài đặt"
])

# ----- HỆ THỐNG PHÂN QUYỀN -----
user_role = st.sidebar.selectbox("Chọn vai trò", ["Admin", "Staff"], index=0)

# ----- BÁN HÀNG -----
if menu == "Bán hàng":
    st.header("Bán hàng POS")

    products = get_products()
    if not products:
        st.warning("Chưa có sản phẩm nào! Vui lòng thêm sản phẩm trước.")
    else:
        df_cart = pd.DataFrame(columns=["Sản phẩm", "Số lượng", "Giá bán", "Thành tiền"])
        with st.form("sale_form"):
            st.subheader("Chọn sản phẩm bán")
            product_choice = st.selectbox("Sản phẩm", [(p.id, p.name) for p in products], format_func=lambda x: x[1])
            quantity = st.number_input("Số lượng", min_value=1, step=1)
            discount = st.number_input("Giảm giá (%)", min_value=0, max_value=100, step=1)
            customer_name = st.text_input("Tên khách hàng", value="Khách lẻ")
            submitted = st.form_submit_button("Thêm vào giỏ")
            if submitted:
                add_to_cart(product_choice[0], quantity, discount, customer_name)
                st.success(f"Đã thêm {quantity} x {product_choice[1]} vào giỏ hàng!")

        # Hiển thị giỏ hàng
        st.subheader("Giỏ hàng hiện tại")
        cart_items = get_cart(customer_name)
        if cart_items:
            total_amount = 0
            for item in cart_items:
                item_total = item['price'] * item['quantity'] * (1 - item['discount']/100)
                total_amount += item_total
                df_cart = pd.concat([df_cart, pd.DataFrame([{
                    "Sản phẩm": item['name'],
                    "Số lượng": item['quantity'],
                    "Giá bán": item['price'],
                    "Thành tiền": item_total
                }])], ignore_index=True)
            st.table(df_cart)
            st.markdown(f"**Tổng thanh toán:** {total_amount:,.0f} đ")
            if st.button("Thanh toán và in hóa đơn"):
                process_payment(customer_name)
                st.success("Thanh toán thành công! Hóa đơn đã được in.")
        else:
            st.info("Giỏ hàng trống.")

# ----- BÁO CÁO DOANH THU -----
if menu == "Báo cáo":
    st.header("Báo cáo và thống kê")

    st.subheader("Doanh thu theo ngày")
    revenue_data = get_revenue_data()  # giả sử trả về danh sách dict: date, total
    if revenue_data:
        df_rev = pd.DataFrame(revenue_data)
        df_rev['Ngày'] = pd.to_datetime(df_rev['date']).dt.strftime("%d-%m-%Y")
        st.bar_chart(df_rev.set_index('Ngày')['total'])
    else:
        st.info("Chưa có dữ liệu doanh thu.")

    st.subheader("Top sản phẩm bán chạy")
    top_products = get_top_products()
    if top_products:
        df_top = pd.DataFrame(top_products)
        st.table(df_top)
    else:
        st.info("Chưa có dữ liệu sản phẩm bán chạy.")

    st.subheader("Khách hàng VIP")
    vip_customers = get_vip_customers()
    if vip_customers:
        df_vip = pd.DataFrame(vip_customers)
        st.table(df_vip)
    else:
        st.info("Chưa có khách VIP nào.")

# ----- CÀI ĐẶT -----
if menu == "Cài đặt":
    st.header("Cài đặt hệ thống POS")
    st.subheader("Quản lý người dùng")
    users = get_users()
    st.table([{"Tên": u.username, "Vai trò": u.role} for u in users])
    st.subheader("Cài đặt khác")
    st.info("Các tính năng nâng cao sẽ được triển khai ở phiên bản sau.")

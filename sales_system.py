import streamlit as st
import pandas as pd
import os
import bcrypt
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy import func
import plotly.express as px
from fpdf import FPDF
import io
import tempfile

# ---------- CẤU HÌNH DATABASE (SQLite tự động chọn đường dẫn) ----------
# Nếu đang chạy trên Streamlit Cloud, dùng /tmp (có quyền ghi)
# Nếu chạy local, dùng file sales.db trong thư mục hiện tại
if os.environ.get('STREAMLIT_CLOUD'):
    DB_PATH = os.path.join(tempfile.gettempdir(), 'sales.db')
else:
    DB_PATH = 'sales.db'

DATABASE_URL = f"sqlite:///{DB_PATH}"
use_row_lock = False  # SQLite không hỗ trợ row lock

# Engine với check_same_thread=False (quan trọng cho Streamlit)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# ---------- ĐỊNH NGHĨA MODELS ----------
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
    image_path = Column(String)  # đường dẫn ảnh local (tạm bỏ cloudinary)
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

# Tạo bảng
Base.metadata.create_all(engine)

# ---------- HÀM TIỆN ÍCH ----------
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

def add_product(name, price, stock, image_file, barcode=None):
    with SessionLocal() as session:
        image_path = ""
        if image_file:
            # Lưu ảnh local vào thư mục uploads (tự tạo nếu chưa có)
            os.makedirs("uploads", exist_ok=True)
            img_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{image_file.name}"
            image_path = os.path.join("uploads", img_name)
            with open(image_path, "wb") as f:
                f.write(image_file.getbuffer())
        product = Product(name=name, price=price, stock=stock, image_path=image_path, barcode=barcode)
        session.add(product)
        session.commit()

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
                os.makedirs("uploads", exist_ok=True)
                img_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{image_file.name}"
                image_path = os.path.join("uploads", img_name)
                with open(image_path, "wb") as f:
                    f.write(image_file.getbuffer())
                product.image_path = image_path
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
                    Product.barcode.isnot(None),
                    Product.barcode.contains(search_term)
                )
            )
        products = query.all()
    return products

def get_customers():
    with SessionLocal() as session:
        customers = session.query(Customer).all()
    return customers

def add_customer(name, phone):
    with SessionLocal() as session:
        cust = Customer(name=name, phone=phone)
        session.add(cust)
        session.commit()

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
        disc = float(session.query(Setting).filter_by(key=key).first().value)
    return disc

def get_loyal_customers():
    with SessionLocal() as session:
        customers = session.query(Customer).filter_by(type='loyal').all()
    return customers

def get_top_vip_customers(limit=10):
    with SessionLocal() as session:
        customers = session.query(Customer).order_by(Customer.total_spent.desc()).limit(limit).all()
    return customers

def record_sale(customer_id, cart_items, discount_percent):
    with SessionLocal() as session:
        try:
            # Kiểm tra tồn kho (không lock vì SQLite)
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
                # Trừ kho
                session.query(Product).filter_by(id=pid).update({Product.stock: Product.stock - qty})
            
            cust = session.query(Customer).filter_by(id=customer_id).first()
            cust.total_spent += final
            cust.total_purchases += 1
            session.commit()
            
            update_customer_type(customer_id)
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
    # Cập nhật lại type
    with SessionLocal() as session:
        for cust in session.query(Customer).all():
            update_customer_type(cust.id)

def generate_pdf_invoice(sale_id, customer_name, customer_phone, customer_type, items, total, discount, final):
    # Font hỗ trợ tiếng Việt (cần có file DejaVuSans.ttf trong thư mục fonts)
    font_path = "fonts/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdf = FPDF()
        pdf.add_font('DejaVu', '', font_path, uni=True)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font('DejaVu', '', 12)
    else:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Arial", size=12)
    
    pdf.cell(200, 10, txt="HÓA ĐƠN BÁN HÀNG", ln=1, align='C')
    pdf.cell(200, 10, txt=f"Mã HD: {sale_id}", ln=1)
    pdf.cell(200, 10, txt=f"Khách hàng: {customer_name} - {customer_phone} ({customer_type})", ln=1)
    pdf.cell(200, 10, txt=f"Ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=1)
    pdf.ln(10)
    
    pdf.set_font('DejaVu', 'B', 10) if os.path.exists(font_path) else pdf.set_font("Arial", 'B', 10)
    pdf.cell(80, 10, "Sản phẩm", 1)
    pdf.cell(30, 10, "SL", 1)
    pdf.cell(40, 10, "Đơn giá", 1)
    pdf.cell(40, 10, "Thành tiền", 1)
    pdf.ln()
    
    pdf.set_font('DejaVu', '', 10) if os.path.exists(font_path) else pdf.set_font("Arial", size=10)
    for item in items:
        pdf.cell(80, 10, item['name'], 1)
        pdf.cell(30, 10, str(item['qty']), 1)
        pdf.cell(40, 10, f"{item['price']:,.0f}", 1)
        pdf.cell(40, 10, f"{item['qty']*item['price']:,.0f}", 1)
        pdf.ln()
    
    pdf.ln(5)
    pdf.cell(200, 10, txt=f"Tổng tiền: {total:,.0f} VNĐ", ln=1)
    pdf.cell(200, 10, txt=f"Giảm giá: {discount:,.0f} VNĐ", ln=1)
    pdf.set_font('DejaVu', 'B', 12) if os.path.exists(font_path) else pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt=f"Thực thu: {final:,.0f} VNĐ", ln=1)
    
    pdf_output = io.BytesIO()
    pdf_output.write(pdf.output(dest='S').encode('latin1'))
    pdf_output.seek(0)
    return pdf_output

# ---------- GIAO DIỆN STREAMLIT ----------
st.set_page_config(page_title="Hệ thống bán hàng", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'cart' not in st.session_state:
    st.session_state.cart = []
if 'sale_step' not in st.session_state:
    st.session_state.sale_step = 1
if 'search_term' not in st.session_state:
    st.session_state.search_term = ""

# Đăng nhập
if not st.session_state.logged_in:
    st.title("🔐 Đăng nhập hệ thống bán hàng")
    with st.form("login_form"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        submit = st.form_submit_button("Đăng nhập")
        if submit:
            role = login(username, password)
            if role:
                st.session_state.logged_in = True
                st.session_state.role = role
                st.success(f"Chào mừng {username} ({role})")
                st.rerun()
            else:
                st.error("Sai tên đăng nhập hoặc mật khẩu")
    st.stop()

def login(username, password):
    with SessionLocal() as session:
        user = session.query(User).filter_by(username=username).first()
        if user and verify_password(password, user.password_hash):
            return user.role
    return None

# ---------- MENU CHÍNH ----------
menu = st.sidebar.radio("Chức năng", 
    ["🏠 Trang chủ", "📦 Quản lý sản phẩm", "🛒 Bán hàng", "👥 Khách hàng", "🔥 Khách thân thiết", "📊 Báo cáo", "⚙️ Cài đặt (Admin)"])

# -------------------- ADMIN --------------------
if st.session_state.role == 'admin':
    if menu == "⚙️ Cài đặt (Admin)":
        st.header("Cài đặt hệ thống")
        with SessionLocal() as session:
            with st.form("settings_form"):
                loyal_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) cho Khách Thân thiết", value=float(session.query(Setting).filter_by(key='loyal_min_spent').first().value))
                loyal_pur = st.number_input("Ngưỡng số lần mua cho Khách Thân thiết", value=int(session.query(Setting).filter_by(key='loyal_min_purchases').first().value))
                longtime_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) cho Khách Lâu năm", value=float(session.query(Setting).filter_by(key='longtime_min_spent').first().value))
                longtime_pur = st.number_input("Ngưỡng số lần mua cho Khách Lâu năm", value=int(session.query(Setting).filter_by(key='longtime_min_purchases').first().value))
                loyal_disc = st.number_input("Giảm giá cho Khách Thân thiết (%)", value=float(session.query(Setting).filter_by(key='loyal_discount').first().value))
                longtime_disc = st.number_input("Giảm giá cho Khách Lâu năm (%)", value=float(session.query(Setting).filter_by(key='longtime_discount').first().value))
                regular_disc = st.number_input("Giảm giá cho Khách Thường (%)", value=float(session.query(Setting).filter_by(key='regular_discount').first().value))
                if st.form_submit_button("Lưu cài đặt"):
                    for k, v in [('loyal_min_spent', loyal_spent), ('loyal_min_purchases', loyal_pur),
                                 ('longtime_min_spent', longtime_spent), ('longtime_min_purchases', longtime_pur),
                                 ('loyal_discount', loyal_disc), ('longtime_discount', longtime_disc),
                                 ('regular_discount', regular_disc)]:
                        setting = session.query(Setting).filter_by(key=k).first()
                        setting.value = str(v)
                    session.commit()
                    st.success("Đã lưu cài đặt! Phân loại khách hàng sẽ tự động cập nhật.")
                    # Cập nhật lại type cho tất cả khách
                    for cust in session.query(Customer).all():
                        update_customer_type(cust.id)
                    st.rerun()
        
        st.subheader("Tải lên danh sách khách hàng (CSV)")
        uploaded_file = st.file_uploader("Chọn file CSV (cột: name, phone, total_spent, total_purchases)", type="csv")
        if uploaded_file:
            upload_customers_csv(uploaded_file)
            st.success("Đã tải lên và cập nhật phân loại khách hàng")
    
    if menu == "📦 Quản lý sản phẩm":
        st.header("Quản lý sản phẩm (Admin)")
        tab1, tab2 = st.tabs(["Thêm sản phẩm", "Sửa/xóa sản phẩm"])
        with tab1:
            with st.form("add_product"):
                name = st.text_input("Tên sản phẩm")
                price = st.number_input("Giá bán", min_value=0.0, step=1000.0)
                stock = st.number_input("Số lượng trong kho", min_value=0, step=1)
                barcode = st.text_input("Mã vạch (tùy chọn)")
                image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
                if st.form_submit_button("Thêm sản phẩm"):
                    if name and price > 0:
                        add_product(name, price, stock, image, barcode)
                        st.success("Đã thêm sản phẩm")
                        st.rerun()
        with tab2:
            products = get_all_products()
            if products:
                prod_dict = {f"{p.id} - {p.name}": p for p in products}
                selected = st.selectbox("Chọn sản phẩm", list(prod_dict.keys()))
                p = prod_dict[selected]
                with st.form("edit_product"):
                    new_name = st.text_input("Tên", p.name)
                    new_price = st.number_input("Giá", value=p.price, step=1000.0)
                    new_stock = st.number_input("Tồn kho", value=p.stock, step=1)
                    new_barcode = st.text_input("Mã vạch", value=p.barcode or "")
                    new_image = st.file_uploader("Thay ảnh mới (nếu có)", type=['png','jpg','jpeg'])
                    if st.form_submit_button("Cập nhật"):
                        update_product(p.id, new_name, new_price, new_stock, new_image, new_barcode)
                        st.success("Đã cập nhật")
                        st.rerun()
                if st.button("Xóa sản phẩm", key="del"):
                    delete_product(p.id)
                    st.success("Đã xóa")
                    st.rerun()
            else:
                st.info("Chưa có sản phẩm nào")
    
    if menu == "📊 Báo cáo":
        st.header("Báo cáo doanh thu & tồn kho")
        with SessionLocal() as session:
            sales_df = pd.read_sql_query("SELECT * FROM sales", session.bind)
            st.subheader("Lịch sử bán hàng")
            st.dataframe(sales_df)
            total_revenue = sales_df['final_amount'].sum() if not sales_df.empty else 0
            st.metric("Tổng doanh thu", f"{total_revenue:,.0f} VNĐ")
            st.subheader("Tồn kho hiện tại")
            products_df = pd.read_sql_query("SELECT name, stock FROM products", session.bind)
            st.dataframe(products_df)
            # Biểu đồ
            if not sales_df.empty:
                df_sales = sales_df.copy()
                df_sales['date'] = pd.to_datetime(df_sales['date']).dt.date
                df_sales = df_sales.groupby('date')['final_amount'].sum().reset_index()
                fig = px.line(df_sales, x='date', y='final_amount', title='Doanh thu theo ngày')
                st.plotly_chart(fig, use_container_width=True)
            # Top sản phẩm
            items = session.query(SaleItem.product_id, func.sum(SaleItem.quantity).label('total_qty')).group_by(SaleItem.product_id).all()
            if items:
                prod_ids = [i[0] for i in items]
                qties = [i[1] for i in items]
                names = [session.query(Product).get(pid).name for pid in prod_ids]
                df_top = pd.DataFrame({'Sản phẩm': names, 'Số lượng bán': qties}).sort_values('Số lượng bán', ascending=False).head(10)
                fig2 = px.bar(df_top, x='Sản phẩm', y='Số lượng bán', title='Top 10 sản phẩm bán chạy')
                st.plotly_chart(fig2, use_container_width=True)
    
    if menu == "🔥 Khách thân thiết":
        st.header("🔥 Danh sách khách hàng thân thiết")
        loyals = get_loyal_customers()
        if loyals:
            df = pd.DataFrame([(c.name, c.phone, c.total_spent, c.total_purchases) for c in loyals],
                              columns=["Tên", "SĐT", "Chi tiêu (VNĐ)", "Số lần mua"])
            st.dataframe(df)
        else:
            st.info("Chưa có khách hàng thân thiết nào.")
        st.subheader("🏆 Top 10 khách hàng VIP (chi tiêu cao nhất)")
        vips = get_top_vip_customers(10)
        if vips:
            df_vip = pd.DataFrame([(c.name, c.phone, c.total_spent, c.total_purchases, c.type) for c in vips],
                                   columns=["Tên", "SĐT", "Chi tiêu (VNĐ)", "Số lần mua", "Loại"])
            st.dataframe(df_vip)
        else:
            st.info("Chưa có dữ liệu khách hàng.")

# -------------------- NHÂN VIÊN --------------------
else:  # staff
    if menu == "🏠 Trang chủ":
        st.header("Chào mừng nhân viên bán hàng")
        st.info("Bạn có thể thêm sản phẩm mới, xem kho, và bán hàng.")
    
    if menu == "📦 Quản lý sản phẩm":
        st.header("Thêm sản phẩm mới (Nhân viên)")
        with st.form("staff_add_product"):
            name = st.text_input("Tên sản phẩm")
            price = st.number_input("Giá bán", min_value=0.0, step=1000.0)
            stock = st.number_input("Số lượng nhập kho", min_value=0, step=1)
            barcode = st.text_input("Mã vạch (tùy chọn)")
            image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
            if st.form_submit_button("Thêm sản phẩm"):
                if name and price > 0:
                    add_product(name, price, stock, image, barcode)
                    st.success("Đã thêm sản phẩm mới")
                    st.rerun()
        st.subheader("Danh sách sản phẩm (chỉ xem)")
        products = get_all_products()
        if products:
            for p in products:
                col1, col2 = st.columns([1, 3])
                with col1:
                    if p.image_path and os.path.exists(p.image_path):
                        st.image(p.image_path, width=100)
                with col2:
                    st.write(f"**{p.name}** - {p.price:,.0f}đ - Tồn: {p.stock}")
        else:
            st.info("Chưa có sản phẩm nào")
    
    if menu == "🛒 Bán hàng":
        st.header("Tạo đơn hàng")
        if st.session_state.sale_step == 1:
            customers = get_customers()
            if not customers:
                st.warning("Chưa có khách hàng. Vui lòng nhập khách mới.")
                with st.form("new_customer"):
                    name = st.text_input("Tên khách hàng")
                    phone = st.text_input("Số điện thoại")
                    if st.form_submit_button("Tạo khách hàng"):
                        add_customer(name, phone)
                        st.rerun()
            else:
                cust_options = {f"{c.name} - {c.phone} ({c.type})": c.id for c in customers}
                selected = st.selectbox("Chọn khách hàng", list(cust_options.keys()))
                if st.button("Chọn khách hàng này"):
                    st.session_state.current_customer = cust_options[selected]
                    st.session_state.sale_step = 2
                    st.rerun()
                with st.expander("Hoặc thêm khách hàng mới"):
                    new_name = st.text_input("Tên mới")
                    new_phone = st.text_input("SĐT mới")
                    if st.button("Thêm và chọn"):
                        add_customer(new_name, new_phone)
                        with SessionLocal() as session:
                            cust = session.query(Customer).filter_by(phone=new_phone).first()
                            st.session_state.current_customer = cust.id
                        st.session_state.sale_step = 2
                        st.rerun()
        else:
            st.subheader("🛒 Giỏ hàng hiện tại")
            if st.session_state.cart:
                # Hiển thị giỏ hàng với nút xóa, tăng giảm
                for idx, item in enumerate(st.session_state.cart):
                    col1, col2, col3, col4, col5 = st.columns([3,1,1,1,1])
                    col1.write(f"{item['name']} - {item['price']:,.0f}đ")
                    col2.write(f"Số lượng: {item['qty']}")
                    if col3.button("➕", key=f"inc_{idx}"):
                        with SessionLocal() as session:
                            prod = session.query(Product).get(item['id'])
                            if prod.stock > item['qty']:
                                st.session_state.cart[idx]['qty'] += 1
                            else:
                                st.warning("Không đủ hàng")
                        st.rerun()
                    if col4.button("➖", key=f"dec_{idx}"):
                        if item['qty'] > 1:
                            st.session_state.cart[idx]['qty'] -= 1
                        else:
                            st.session_state.cart.pop(idx)
                        st.rerun()
                    if col5.button("❌", key=f"del_{idx}"):
                        st.session_state.cart.pop(idx)
                        st.rerun()
                
                total = sum(item['price'] * item['qty'] for item in st.session_state.cart)
                discount = get_discount_for_customer(st.session_state.current_customer)
                discount_amt = total * discount / 100
                final = total - discount_amt
                st.metric("Tổng tiền", f"{total:,.0f} VNĐ")
                st.write(f"Giảm giá {discount}% : -{discount_amt:,.0f} VNĐ")
                st.metric("Thực thu", f"{final:,.0f} VNĐ")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Thanh toán"):
                        cart_items = [(item['id'], item['qty'], item['price']) for item in st.session_state.cart]
                        try:
                            sale_id, final_amt, disc_amt = record_sale(st.session_state.current_customer, cart_items, discount)
                            st.success(f"Thanh toán thành công! Hóa đơn #{sale_id}")
                            with SessionLocal() as session:
                                cust = session.query(Customer).get(st.session_state.current_customer)
                                pdf_buffer = generate_pdf_invoice(sale_id, cust.name, cust.phone, cust.type,
                                                                  st.session_state.cart, total, disc_amt, final_amt)
                            st.download_button("📄 Tải hóa đơn PDF", data=pdf_buffer, file_name=f"invoice_{sale_id}.pdf", mime="application/pdf")
                            st.session_state.cart = []
                            st.session_state.sale_step = 1
                            st.session_state.current_customer = None
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                with col2:
                    if st.button("Hủy đơn hàng"):
                        st.session_state.cart = []
                        st.session_state.sale_step = 1
                        st.session_state.current_customer = None
                        st.rerun()
            else:
                st.info("Giỏ hàng trống. Hãy thêm sản phẩm bên dưới.")
            
            st.subheader("Thêm sản phẩm vào giỏ")
            search = st.text_input("🔍 Tìm kiếm (tên hoặc mã vạch)", value=st.session_state.search_term)
            if search != st.session_state.search_term:
                st.session_state.search_term = search
                st.rerun()
            products = get_all_products(st.session_state.search_term)
            if products:
                for p in products:
                    col1, col2, col3, col4 = st.columns([1,3,1,1])
                    with col1:
                        if p.image_path and os.path.exists(p.image_path):
                            st.image(p.image_path, width=80)
                    with col2:
                        st.write(f"**{p.name}** - {p.price:,.0f}đ (còn {p.stock})")
                    with col3:
                        qty = st.number_input("SL", min_value=1, max_value=p.stock, value=1, key=f"qty_{p.id}")
                    with col4:
                        if st.button("➕ Thêm", key=f"add_{p.id}"):
                            found = False
                            for item in st.session_state.cart:
                                if item['id'] == p.id:
                                    new_qty = item['qty'] + qty
                                    if new_qty <= p.stock:
                                        item['qty'] = new_qty
                                    else:
                                        st.warning("Vượt quá tồn kho")
                                    found = True
                                    break
                            if not found:
                                st.session_state.cart.append({'id': p.id, 'name': p.name, 'price': p.price, 'qty': qty})
                            st.rerun()
            else:
                st.info("Không tìm thấy sản phẩm")
    
    if menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng (chỉ xem)")
        customers = get_customers()
        if customers:
            df = pd.DataFrame([(c.id, c.name, c.phone, c.total_spent, c.total_purchases, c.type) for c in customers],
                              columns=['ID', 'Tên', 'SĐT', 'Chi tiêu', 'Số lần mua', 'Loại'])
            st.dataframe(df)
        else:
            st.info("Chưa có khách hàng")
    
    if menu == "🔥 Khách thân thiết":
        st.header("🔥 Danh sách khách hàng thân thiết")
        loyals = get_loyal_customers()
        if loyals:
            df = pd.DataFrame([(c.name, c.phone, c.total_spent, c.total_purchases) for c in loyals],
                              columns=["Tên", "SĐT", "Chi tiêu (VNĐ)", "Số lần mua"])
            st.dataframe(df)
        else:
            st.info("Chưa có khách hàng thân thiết nào.")
        st.subheader("🏆 Top 10 khách hàng VIP")
        vips = get_top_vip_customers(10)
        if vips:
            df_vip = pd.DataFrame([(c.name, c.phone, c.total_spent, c.total_purchases, c.type) for c in vips],
                                   columns=["Tên", "SĐT", "Chi tiêu (VNĐ)", "Số lần mua", "Loại"])
            st.dataframe(df_vip)
        else:
            st.info("Chưa có dữ liệu khách hàng.")
    
    if menu == "📊 Báo cáo":
        st.header("Xem báo cáo (Nhân viên chỉ xem được lịch sử bán hàng)")
        with SessionLocal() as session:
            sales = pd.read_sql_query("SELECT * FROM sales", session.bind)
            st.dataframe(sales)

# Đăng xuất
if st.sidebar.button("Đăng xuất"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

import streamlit as st
import sqlite3
import pandas as pd
from PIL import Image
import os
import hashlib
from datetime import datetime

# ---------- KHỞI TẠO DATABASE ----------
def init_db():
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    
    # Bảng người dùng
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    
    # Bảng sản phẩm
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT, price REAL, stock INTEGER, image_path TEXT)''')
    
    # Bảng khách hàng
    c.execute('''CREATE TABLE IF NOT EXISTS customers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT, phone TEXT, total_spent REAL, total_purchases INTEGER,
                  type TEXT)''')
    
    # Bảng hóa đơn
    c.execute('''CREATE TABLE IF NOT EXISTS sales
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  customer_id INTEGER, date TEXT, total_amount REAL,
                  discount REAL, final_amount REAL)''')
    
    # Bảng chi tiết hóa đơn
    c.execute('''CREATE TABLE IF NOT EXISTS sale_items
                 (sale_id INTEGER, product_id INTEGER, quantity INTEGER, price REAL)''')
    
    # Bảng cài đặt (ngưỡng phân loại và giảm giá)
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    
    # Thêm dữ liệu mặc định nếu chưa có
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users VALUES (?, ?, ?)", 
                  ('admin', hashlib.sha256('admin123'.encode()).hexdigest(), 'admin'))
        c.execute("INSERT INTO users VALUES (?, ?, ?)", 
                  ('staff', hashlib.sha256('staff123'.encode()).hexdigest(), 'staff'))
    
    # Cài đặt ngưỡng mặc định
    default_settings = {
        'loyal_min_spent': '5000000',
        'loyal_min_purchases': '10',
        'longtime_min_spent': '2000000',
        'longtime_min_purchases': '5',
        'loyal_discount': '5',
        'longtime_discount': '2',
        'regular_discount': '0'
    }
    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    
    conn.commit()
    conn.close()

init_db()

# ---------- HÀM TIỆN ÍCH ----------
def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def login(username, password):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    c.execute("SELECT password, role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row and row[0] == hash_password(password):
        return row[1]
    return None

def get_all_products():
    conn = sqlite3.connect('sales.db')
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()
    return df

def add_product(name, price, stock, image):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    # Lưu ảnh
    img_path = ""
    if image:
        os.makedirs("uploads", exist_ok=True)
        img_path = f"uploads/{datetime.now().strftime('%Y%m%d%H%M%S')}_{image.name}"
        with open(img_path, "wb") as f:
            f.write(image.getbuffer())
    c.execute("INSERT INTO products (name, price, stock, image_path) VALUES (?,?,?,?)",
              (name, price, stock, img_path))
    conn.commit()
    conn.close()

def update_product(product_id, name, price, stock, image):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    if image:
        os.makedirs("uploads", exist_ok=True)
        img_path = f"uploads/{datetime.now().strftime('%Y%m%d%H%M%S')}_{image.name}"
        with open(img_path, "wb") as f:
            f.write(image.getbuffer())
        c.execute("UPDATE products SET name=?, price=?, stock=?, image_path=? WHERE id=?",
                  (name, price, stock, img_path, product_id))
    else:
        c.execute("UPDATE products SET name=?, price=?, stock=? WHERE id=?",
                  (name, price, stock, product_id))
    conn.commit()
    conn.close()

def delete_product(product_id):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()

def get_customers():
    conn = sqlite3.connect('sales.db')
    df = pd.read_sql_query("SELECT * FROM customers", conn)
    conn.close()
    return df

def add_customer(name, phone):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    c.execute("INSERT INTO customers (name, phone, total_spent, total_purchases, type) VALUES (?,?,0,0,'regular')",
              (name, phone))
    conn.commit()
    conn.close()

def update_customer_type(customer_id):
    """Phân loại lại khách hàng dựa trên ngưỡng hiện tại"""
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    # Lấy ngưỡng
    c.execute("SELECT value FROM settings WHERE key='loyal_min_spent'")
    loyal_spent = float(c.fetchone()[0])
    c.execute("SELECT value FROM settings WHERE key='loyal_min_purchases'")
    loyal_pur = int(c.fetchone()[0])
    c.execute("SELECT value FROM settings WHERE key='longtime_min_spent'")
    longtime_spent = float(c.fetchone()[0])
    c.execute("SELECT value FROM settings WHERE key='longtime_min_purchases'")
    longtime_pur = int(c.fetchone()[0])
    
    c.execute("SELECT total_spent, total_purchases FROM customers WHERE id=?", (customer_id,))
    spent, pur = c.fetchone()
    if spent >= loyal_spent and pur >= loyal_pur:
        cust_type = 'loyal'
    elif spent >= longtime_spent and pur >= longtime_pur:
        cust_type = 'longtime'
    else:
        cust_type = 'regular'
    c.execute("UPDATE customers SET type=? WHERE id=?", (cust_type, customer_id))
    conn.commit()
    conn.close()

def upload_customers_csv(file):
    df = pd.read_csv(file)
    conn = sqlite3.connect('sales.db')
    for _, row in df.iterrows():
        name = row.get('name')
        phone = str(row.get('phone'))
        spent = float(row.get('total_spent', 0))
        purchases = int(row.get('total_purchases', 0))
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO customers (name, phone, total_spent, total_purchases, type) VALUES (?,?,?,?,'regular')",
                  (name, phone, spent, purchases))
        conn.commit()
        # Cập nhật type
        c.execute("SELECT id FROM customers WHERE phone=?", (phone,))
        cust_id = c.fetchone()
        if cust_id:
            update_customer_type(cust_id[0])
    conn.close()

def record_sale(customer_id, cart_items, discount_percent):
    """cart_items: list of (product_id, quantity, price)"""
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    total = sum(q * p for _, q, p in cart_items)
    discount_amount = total * discount_percent / 100
    final = total - discount_amount
    
    # Ghi hóa đơn
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO sales (customer_id, date, total_amount, discount, final_amount) VALUES (?,?,?,?,?)",
              (customer_id, now, total, discount_amount, final))
    sale_id = c.lastrowid
    
    # Ghi chi tiết và trừ kho
    for pid, qty, price in cart_items:
        c.execute("INSERT INTO sale_items (sale_id, product_id, quantity, price) VALUES (?,?,?,?)",
                  (sale_id, pid, qty, price))
        c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (qty, pid))
    
    # Cập nhật thông tin khách hàng
    c.execute("SELECT total_spent, total_purchases FROM customers WHERE id=?", (customer_id,))
    old_spent, old_pur = c.fetchone()
    new_spent = old_spent + final
    new_pur = old_pur + 1
    c.execute("UPDATE customers SET total_spent=?, total_purchases=? WHERE id=?", (new_spent, new_pur, customer_id))
    update_customer_type(customer_id)
    
    conn.commit()
    conn.close()
    return sale_id, final, discount_amount

def get_discount_for_customer(customer_id):
    conn = sqlite3.connect('sales.db')
    c = conn.cursor()
    c.execute("SELECT type FROM customers WHERE id=?", (customer_id,))
    cust_type = c.fetchone()[0]
    key = f"{cust_type}_discount"
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    discount = float(c.fetchone()[0])
    conn.close()
    return discount

# ---------- GIAO DIỆN STREAMLIT ----------
st.set_page_config(page_title="Hệ thống bán hàng", layout="wide")

# Khởi tạo session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'cart' not in st.session_state:
    st.session_state.cart = []  # list of (product_id, name, price, quantity)
if 'sale_step' not in st.session_state:
    st.session_state.sale_step = 1

# Form đăng nhập
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

# ---------- MENU CHÍNH ----------
menu = st.sidebar.radio("Chức năng", 
    ["🏠 Trang chủ", "📦 Quản lý sản phẩm", "🛒 Bán hàng", "👥 Khách hàng", "📊 Báo cáo", "⚙️ Cài đặt (Admin)"])

# -------------------- ADMIN --------------------
if st.session_state.role == 'admin':
    if menu == "⚙️ Cài đặt (Admin)":
        st.header("Cài đặt hệ thống")
        with st.form("settings_form"):
            loyal_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) cho Khách Thân thiết", value=float(st.session_state.get('loyal_spent', 5000000)))
            loyal_pur = st.number_input("Ngưỡng số lần mua cho Khách Thân thiết", value=int(st.session_state.get('loyal_pur', 10)))
            longtime_spent = st.number_input("Ngưỡng chi tiêu (VNĐ) cho Khách Lâu năm", value=float(st.session_state.get('longtime_spent', 2000000)))
            longtime_pur = st.number_input("Ngưỡng số lần mua cho Khách Lâu năm", value=int(st.session_state.get('longtime_pur', 5)))
            loyal_disc = st.number_input("Giảm giá cho Khách Thân thiết (%)", value=float(st.session_state.get('loyal_disc', 5)))
            longtime_disc = st.number_input("Giảm giá cho Khách Lâu năm (%)", value=float(st.session_state.get('longtime_disc', 2)))
            regular_disc = st.number_input("Giảm giá cho Khách Thường (%)", value=float(st.session_state.get('regular_disc', 0)))
            submitted = st.form_submit_button("Lưu cài đặt")
            if submitted:
                conn = sqlite3.connect('sales.db')
                c = conn.cursor()
                c.execute("UPDATE settings SET value=? WHERE key='loyal_min_spent'", (str(loyal_spent),))
                c.execute("UPDATE settings SET value=? WHERE key='loyal_min_purchases'", (str(loyal_pur),))
                c.execute("UPDATE settings SET value=? WHERE key='longtime_min_spent'", (str(longtime_spent),))
                c.execute("UPDATE settings SET value=? WHERE key='longtime_min_purchases'", (str(longtime_pur),))
                c.execute("UPDATE settings SET value=? WHERE key='loyal_discount'", (str(loyal_disc),))
                c.execute("UPDATE settings SET value=? WHERE key='longtime_discount'", (str(longtime_disc),))
                c.execute("UPDATE settings SET value=? WHERE key='regular_discount'", (str(regular_disc),))
                conn.commit()
                conn.close()
                st.success("Đã lưu cài đặt! Phân loại khách hàng sẽ tự động cập nhật.")
                # Cập nhật lại type cho tất cả khách
                conn = sqlite3.connect('sales.db')
                customers = pd.read_sql_query("SELECT id FROM customers", conn)
                for cid in customers['id']:
                    update_customer_type(cid)
                conn.close()
                st.rerun()
        
        st.subheader("Tải lên danh sách khách hàng (CSV)")
        uploaded_file = st.file_uploader("Chọn file CSV (cột: name, phone, total_spent, total_purchases)", type="csv")
        if uploaded_file:
            upload_customers_csv(uploaded_file)
            st.success("Đã tải lên và cập nhật phân loại khách hàng")
    
    if menu == "👥 Khách hàng":
        st.header("Quản lý khách hàng")
        customers = get_customers()
        st.dataframe(customers)
        with st.expander("Thêm khách hàng mới"):
            name = st.text_input("Tên")
            phone = st.text_input("SĐT")
            if st.button("Thêm"):
                add_customer(name, phone)
                st.rerun()
        # Admin có thể sửa thông tin khách hàng
        st.subheader("Chỉnh sửa khách hàng")
        cust_list = customers[['id','name','phone','total_spent','total_purchases','type']].to_dict('records')
        if cust_list:
            selected = st.selectbox("Chọn khách hàng", cust_list, format_func=lambda x: f"{x['name']} - {x['phone']} - {x['type']}")
            new_name = st.text_input("Tên mới", selected['name'])
            new_phone = st.text_input("SĐT mới", selected['phone'])
            if st.button("Cập nhật"):
                conn = sqlite3.connect('sales.db')
                c = conn.cursor()
                c.execute("UPDATE customers SET name=?, phone=? WHERE id=?", (new_name, new_phone, selected['id']))
                conn.commit()
                conn.close()
                st.success("Đã cập nhật")
                st.rerun()
    
    if menu == "📊 Báo cáo":
        st.header("Báo cáo doanh thu & tồn kho")
        conn = sqlite3.connect('sales.db')
        sales_df = pd.read_sql_query("SELECT * FROM sales", conn)
        st.subheader("Lịch sử bán hàng")
        st.dataframe(sales_df)
        total_revenue = sales_df['final_amount'].sum() if not sales_df.empty else 0
        st.metric("Tổng doanh thu", f"{total_revenue:,.0f} VNĐ")
        st.subheader("Tồn kho hiện tại")
        products_df = pd.read_sql_query("SELECT name, stock FROM products", conn)
        st.dataframe(products_df)
        conn.close()
    
    if menu == "📦 Quản lý sản phẩm":
        st.header("Quản lý sản phẩm (Admin)")
        tab1, tab2 = st.tabs(["Thêm sản phẩm", "Sửa/xóa sản phẩm"])
        with tab1:
            with st.form("add_product"):
                name = st.text_input("Tên sản phẩm")
                price = st.number_input("Giá bán", min_value=0.0, step=1000.0)
                stock = st.number_input("Số lượng trong kho", min_value=0, step=1)
                image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
                if st.form_submit_button("Thêm sản phẩm"):
                    add_product(name, price, stock, image)
                    st.success("Đã thêm sản phẩm")
                    st.rerun()
        with tab2:
            products = get_all_products()
            if not products.empty:
                product_list = products[['id','name','price','stock']].to_dict('records')
                selected = st.selectbox("Chọn sản phẩm", product_list, format_func=lambda x: f"{x['name']} - {x['price']:,.0f}đ")
                with st.form("edit_product"):
                    new_name = st.text_input("Tên", selected['name'])
                    new_price = st.number_input("Giá", value=float(selected['price']), step=1000.0)
                    new_stock = st.number_input("Tồn kho", value=int(selected['stock']), step=1)
                    new_image = st.file_uploader("Thay ảnh mới (nếu có)", type=['png','jpg','jpeg'])
                    if st.form_submit_button("Cập nhật"):
                        update_product(selected['id'], new_name, new_price, new_stock, new_image)
                        st.success("Đã cập nhật")
                        st.rerun()
                if st.button("Xóa sản phẩm", key="del"):
                    delete_product(selected['id'])
                    st.success("Đã xóa")
                    st.rerun()
            else:
                st.info("Chưa có sản phẩm nào")

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
            image = st.file_uploader("Hình ảnh", type=['png','jpg','jpeg'])
            if st.form_submit_button("Thêm sản phẩm"):
                add_product(name, price, stock, image)
                st.success("Đã thêm sản phẩm mới")
                st.rerun()
        st.subheader("Danh sách sản phẩm (chỉ xem)")
        products = get_all_products()
        st.dataframe(products[['name','price','stock']])
    
    if menu == "🛒 Bán hàng":
        st.header("Tạo đơn hàng")
        
        # Bước 1: Chọn hoặc thêm khách hàng
        if st.session_state.sale_step == 1:
            customers = get_customers()
            if customers.empty:
                st.warning("Chưa có khách hàng. Vui lòng nhập khách mới.")
                with st.form("new_customer"):
                    name = st.text_input("Tên khách hàng")
                    phone = st.text_input("Số điện thoại")
                    if st.form_submit_button("Tạo khách hàng"):
                        add_customer(name, phone)
                        st.rerun()
            else:
                cust_options = customers.to_dict('records')
                selected_cust = st.selectbox("Chọn khách hàng", cust_options, format_func=lambda x: f"{x['name']} - {x['phone']} ({x['type']})")
                if st.button("Chọn khách hàng này"):
                    st.session_state.current_customer = selected_cust['id']
                    st.session_state.sale_step = 2
                    st.rerun()
                with st.expander("Hoặc thêm khách hàng mới"):
                    new_name = st.text_input("Tên mới")
                    new_phone = st.text_input("SĐT mới")
                    if st.button("Thêm và chọn"):
                        add_customer(new_name, new_phone)
                        conn = sqlite3.connect('sales.db')
                        c = conn.cursor()
                        c.execute("SELECT id FROM customers WHERE phone=?", (new_phone,))
                        new_id = c.fetchone()[0]
                        conn.close()
                        st.session_state.current_customer = new_id
                        st.session_state.sale_step = 2
                        st.rerun()
        
        # Bước 2: Thêm sản phẩm vào giỏ
        elif st.session_state.sale_step == 2:
            st.subheader("Giỏ hàng hiện tại")
            if st.session_state.cart:
                cart_df = pd.DataFrame(st.session_state.cart, columns=['id','name','price','qty'])
                cart_df['Thành tiền'] = cart_df['price'] * cart_df['qty']
                st.dataframe(cart_df[['name','price','qty','Thành tiền']])
                total = cart_df['Thành tiền'].sum()
                # Lấy giảm giá
                cust_id = st.session_state.current_customer
                discount = get_discount_for_customer(cust_id)
                discount_amount = total * discount / 100
                final_total = total - discount_amount
                st.metric("Tổng tiền", f"{total:,.0f} VNĐ")
                st.write(f"Giảm giá {discount}% : -{discount_amount:,.0f} VNĐ")
                st.metric("Thành tiền", f"{final_total:,.0f} VNĐ", delta=f"-{discount}%")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Thanh toán"):
                        # Ghi nhận bán hàng
                        cart_items = [(item[0], item[3], item[2]) for item in st.session_state.cart]  # id, qty, price
                        sale_id, final_amt, disc_amt = record_sale(cust_id, cart_items, discount)
                        st.success(f"Đã bán hàng thành công! Hóa đơn #{sale_id} - {final_amt:,.0f} VNĐ")
                        # In hóa đơn dạng text
                        st.subheader("🧾 HÓA ĐƠN")
                        conn = sqlite3.connect('sales.db')
                        cust_info = pd.read_sql_query(f"SELECT name, phone, type FROM customers WHERE id={cust_id}", conn)
                        st.write(f"Khách hàng: {cust_info.iloc[0]['name']} - {cust_info.iloc[0]['phone']} - Loại: {cust_info.iloc[0]['type']}")
                        st.write(f"Ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
                        st.write("Chi tiết:")
                        for item in st.session_state.cart:
                            st.write(f"- {item[1]}: {item[3]} x {item[2]:,.0f}đ = {item[3]*item[2]:,.0f}đ")
                        st.write(f"Tổng: {total:,.0f}đ")
                        st.write(f"Giảm giá ({discount}%): -{discount_amount:,.0f}đ")
                        st.write(f"Thực thu: {final_amt:,.0f}đ")
                        conn.close()
                        # Reset giỏ hàng và quay lại bước 1
                        st.session_state.cart = []
                        st.session_state.sale_step = 1
                        st.session_state.current_customer = None
                        st.rerun()
                with col2:
                    if st.button("Hủy đơn hàng"):
                        st.session_state.cart = []
                        st.session_state.sale_step = 1
                        st.session_state.current_customer = None
                        st.rerun()
            else:
                st.info("Giỏ hàng trống. Hãy thêm sản phẩm bên dưới.")
            
            st.subheader("Thêm sản phẩm vào giỏ")
            products = get_all_products()
            if not products.empty:
                prod_options = products.to_dict('records')
                selected_prod = st.selectbox("Chọn sản phẩm", prod_options, format_func=lambda x: f"{x['name']} - {x['price']:,.0f}đ (còn {x['stock']})")
                qty = st.number_input("Số lượng", min_value=1, max_value=selected_prod['stock'], step=1)
                if st.button("Thêm vào giỏ"):
                    # Kiểm tra xem sản phẩm đã có trong giỏ chưa
                    found = False
                    new_cart = []
                    for item in st.session_state.cart:
                        if item[0] == selected_prod['id']:
                            new_qty = item[3] + qty
                            if new_qty <= selected_prod['stock']:
                                new_cart.append((item[0], item[1], item[2], new_qty))
                            else:
                                st.error("Vượt quá số lượng tồn kho")
                                found = True
                                new_cart = st.session_state.cart
                                break
                            found = True
                        else:
                            new_cart.append(item)
                    if not found:
                        new_cart.append((selected_prod['id'], selected_prod['name'], selected_prod['price'], qty))
                    st.session_state.cart = new_cart
                    st.rerun()
            else:
                st.warning("Chưa có sản phẩm nào. Hãy thêm sản phẩm trước khi bán.")
    
    if menu == "👥 Khách hàng":
        st.header("Danh sách khách hàng (chỉ xem)")
        customers = get_customers()
        st.dataframe(customers)
    
    if menu == "📊 Báo cáo":
        st.header("Xem báo cáo (Nhân viên chỉ xem được lịch sử bán hàng)")
        conn = sqlite3.connect('sales.db')
        sales = pd.read_sql_query("SELECT * FROM sales", conn)
        st.dataframe(sales)
        conn.close()

# Nút đăng xuất ở sidebar
if st.sidebar.button("Đăng xuất"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
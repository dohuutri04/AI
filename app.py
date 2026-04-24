from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, secrets, re
import json
from functools import wraps
from datetime import datetime, timedelta
from services.ai_personalization import generate_ai_personalization as ai_generate_personalization
from services.upload_service import UploadService, UploadServiceError

# =============================================================================
# EDUCONNECT FLASK APP
# -----------------------------------------------------------------------------
# File này là entrypoint backend:
# - Khởi tạo app + kết nối SQLite
# - Định nghĩa middleware phân quyền
# - Định nghĩa toàn bộ route user/admin
# - Gọi AI service để trả dữ liệu cá nhân hóa
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'educonnect_secret_key_2024_dev_only')
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'elearning.db')
upload_service = UploadService()

# ---- Database helpers --------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_course_image_column(conn):
    """
    Tuong thich schema cu/moi:
    - schema cu dung cot `image`
    - schema moi dung cot `thumbnail`
    """
    cols = {r[1] for r in conn.execute('PRAGMA table_info(courses)').fetchall()}
    if 'thumbnail' in cols:
        return 'thumbnail'
    if 'image' in cols:
        return 'image'
    return None

def ensure_course_files_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS course_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        file_url TEXT NOT NULL,
        file_name TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id)
    )''')


def ensure_teacher_recruitment_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS course_teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        role_in_course TEXT DEFAULT 'teacher',
        status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive')),
        joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(course_id, teacher_id),
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(teacher_id) REFERENCES users(id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS course_teacher_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        invited_user_id INTEGER NOT NULL,
        invited_by INTEGER NOT NULL,
        message TEXT DEFAULT '',
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
        expires_at DATETIME DEFAULT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(invited_user_id) REFERENCES users(id),
        FOREIGN KEY(invited_by) REFERENCES users(id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS teacher_job_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        requirements TEXT DEFAULT '',
        status TEXT DEFAULT 'open' CHECK(status IN ('open','closed')),
        deadline DATETIME DEFAULT NULL,
        created_by INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS teacher_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_post_id INTEGER NOT NULL,
        applicant_id INTEGER NOT NULL,
        bio TEXT NOT NULL,
        experience_summary TEXT DEFAULT '',
        contact_email TEXT NOT NULL,
        contact_phone TEXT DEFAULT '',
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','shortlisted','rejected','accepted')),
        review_note TEXT DEFAULT '',
        reviewed_by INTEGER DEFAULT NULL,
        reviewed_at DATETIME DEFAULT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(job_post_id, applicant_id),
        FOREIGN KEY(job_post_id) REFERENCES teacher_job_posts(id),
        FOREIGN KEY(applicant_id) REFERENCES users(id),
        FOREIGN KEY(reviewed_by) REFERENCES users(id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS teacher_application_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        file_type TEXT DEFAULT 'other' CHECK(file_type IN ('cv','certificate','avatar','other')),
        storage_provider TEXT NOT NULL,
        public_url TEXT NOT NULL,
        storage_key TEXT NOT NULL,
        mime_type TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(application_id) REFERENCES teacher_applications(id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS teacher_application_read_states (
        user_id INTEGER PRIMARY KEY,
        last_seen_at DATETIME DEFAULT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')


def is_course_owner(conn, course_id, user_id):
    row = conn.execute('SELECT id FROM courses WHERE id=? AND instructor_id=?', (course_id, user_id)).fetchone()
    return bool(row)


def can_manage_course(conn, course_id, user_id):
    if is_course_owner(conn, course_id, user_id):
        return True
    ensure_teacher_recruitment_tables(conn)
    row = conn.execute(
        'SELECT id FROM course_teachers WHERE course_id=? AND teacher_id=? AND status="active"',
        (course_id, user_id)
    ).fetchone()
    return bool(row)


def save_teacher_application_file_local(file_storage, application_id, file_type, allowed_exts):
    safe_name = secure_filename(file_storage.filename or '')
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in allowed_exts:
        raise UploadServiceError(f'Định dạng file không hợp lệ: {ext}')
    upload_dir = os.path.join(app.static_folder, 'files', 'teacher-applications')
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"application_{application_id}_{file_type}_{secrets.token_hex(6)}{ext}"
    abs_path = os.path.join(upload_dir, stored_name)
    file_storage.save(abs_path)
    public_url = url_for('static', filename=f'files/teacher-applications/{stored_name}')
    size_bytes = 0
    try:
        size_bytes = os.path.getsize(abs_path)
    except Exception:
        size_bytes = 0
    return {
        'provider': 'local',
        'public_url': public_url,
        'key': f'local/{stored_name}',
        'mime_type': file_storage.mimetype or 'application/octet-stream',
        'size': size_bytes,
    }


def api_ok(data=None, message='OK'):
    return jsonify({'success': True, 'message': message, 'data': data or {}, 'error_code': None})


def api_error(message, error_code='BAD_REQUEST', status=400):
    return jsonify({'success': False, 'message': message, 'data': None, 'error_code': error_code}), status

def init_db():
    with open('database.sql', 'r', encoding='utf-8') as f:
        sql = f.read()
    conn = get_db()
    conn.executescript(sql)
    ensure_teacher_recruitment_tables(conn)
    conn.commit()
    conn.close()

# ---- Auth guards (route protection) -----------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục.', 'warning')
            return redirect(url_for('trang_chu'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('admin_login'))
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or not user['is_admin']:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    if 'user_id' in session:
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        return user
    return None


def generate_ai_personalization(user_id):
    """
    Wrapper gọn cho AI personalization service.
    Tách logic sang module riêng để app.py dễ đọc/sửa.
    """
    return ai_generate_personalization(user_id=user_id, get_db=get_db, logger=app.logger)

# ---- Global context cho templates -------------------------------------------
@app.context_processor
def inject_user():
    return {'current_user': get_current_user()}

@app.context_processor
def admin_helpers():
    def get_contact_count():
        try:
            conn = get_db()
            n = conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
            conn.close()
            return n
        except:
            return 0
    return {'get_contact_count': get_contact_count}


@app.context_processor
def teacher_application_notifications():
    if 'user_id' not in session:
        return {'header_app_update_count': 0}
    try:
        conn = get_db()
        ensure_teacher_recruitment_tables(conn)
        user = conn.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or user['is_admin']:
            conn.close()
            return {'header_app_update_count': 0}
        count = conn.execute(
            'SELECT COUNT(*) as n '
            'FROM teacher_applications a '
            'WHERE a.applicant_id=? '
            'AND a.reviewed_at IS NOT NULL '
            'AND datetime(a.reviewed_at) > datetime(COALESCE((SELECT last_seen_at FROM teacher_application_read_states WHERE user_id=?), "1970-01-01T00:00:00"))',
            (session['user_id'], session['user_id'])
        ).fetchone()['n']
        conn.close()
        return {'header_app_update_count': int(count or 0)}
    except Exception:
        return {'header_app_update_count': 0}

# =============================================================================
# PUBLIC ROUTES
# Các route mở cho người dùng chưa đăng nhập:
# - trang chủ, danh sách khóa học, tìm kiếm, auth, quên mật khẩu
# =============================================================================
@app.route('/')
def trang_chu():
    conn = get_db()
    featured_courses = conn.execute(
        'SELECT c.*, u.name as instructor_name, cat.name as category_name '
        'FROM courses c LEFT JOIN users u ON c.instructor_id=u.id '
        'LEFT JOIN categories cat ON c.category_id=cat.id '
        'WHERE c.is_featured=1 LIMIT 6'
    ).fetchall()
    stats = {
        'students': conn.execute('SELECT COUNT(*) FROM users WHERE is_admin=0').fetchone()[0],
        'courses':  conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0],
        'lessons':  conn.execute('SELECT COALESCE(SUM(total_lessons),0) FROM courses').fetchone()[0],
        'instructors': 3
    }
    reviews  = conn.execute('SELECT r.*, u.name as user_name FROM reviews r JOIN users u ON r.user_id=u.id ORDER BY r.created_at DESC LIMIT 6').fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('trang-chu.html', featured_courses=featured_courses, stats=stats, reviews=reviews, categories=categories)

@app.route('/khoa-hoc')
def tat_ca_khoa_hoc():
    q = request.args.get('q', '')
    category = request.args.get('category', '')
    price_filter = request.args.get('price', '')
    level = request.args.get('level', '')
    page = int(request.args.get('page', 1))
    per_page = 9
    conn = get_db()
    current_user = get_current_user()

    base = ('SELECT c.*, u.name as instructor_name, cat.name as category_name '
            'FROM courses c LEFT JOIN users u ON c.instructor_id=u.id '
            'LEFT JOIN categories cat ON c.category_id=cat.id WHERE 1=1')
    params = []
    if q:        base += ' AND c.title LIKE ?'; params.append(f'%{q}%')
    if category: base += ' AND cat.slug=?';     params.append(category)
    if level:    base += ' AND c.level=?';      params.append(level)
    if price_filter == 'free': base += ' AND c.price=0'
    elif price_filter == 'paid': base += ' AND c.price>0'
    total   = conn.execute(f'SELECT COUNT(*) FROM ({base})', params).fetchone()[0]
    courses = conn.execute(base + f' ORDER BY c.id DESC LIMIT {per_page} OFFSET {(page-1)*per_page}', params).fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()

    # Check enrollment status for current user
    enrolled_ids = set()
    created_ids = set()
    first_lesson_ids = {}
    if current_user:
        rows = conn.execute('SELECT course_id FROM enrollments WHERE user_id=?', (current_user['id'],)).fetchall()
        enrolled_ids = {r['course_id'] for r in rows}
        rows2 = conn.execute('SELECT id FROM courses WHERE instructor_id=?', (current_user['id'],)).fetchall()
        created_ids = {r['id'] for r in rows2}
        # Lấy bài học đầu tiên của mỗi khóa đã đăng ký
        if enrolled_ids:
            placeholders = ','.join('?' * len(enrolled_ids))
            rows3 = conn.execute(
                f'SELECT course_id, MIN(id) as first_id FROM lessons WHERE course_id IN ({placeholders}) GROUP BY course_id',
                list(enrolled_ids)
            ).fetchall()
            first_lesson_ids = {r['course_id']: r['first_id'] for r in rows3}
    conn.close()
    return render_template('tat-ca-khoa-hoc.html', courses=courses, categories=categories,
                           total=total, page=page, total_pages=(total+per_page-1)//per_page,
                           q=q, selected_category=category, price_filter=price_filter, level=level,
                           enrolled_ids=enrolled_ids, created_ids=created_ids,
                           first_lesson_ids=first_lesson_ids)

@app.route('/search')
def search():
    q = request.args.get('q', '')
    conn = get_db()
    results = conn.execute(
        'SELECT c.*, u.name as instructor_name FROM courses c LEFT JOIN users u ON c.instructor_id=u.id WHERE c.title LIKE ? LIMIT 5',
        (f'%{q}%',)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in results])

@app.route('/gioi-thieu')
def gioi_thieu():
    conn = get_db()
    instructors = conn.execute('SELECT DISTINCT u.* FROM users u JOIN courses c ON c.instructor_id=u.id WHERE u.is_admin=0 LIMIT 3').fetchall()
    conn.close()
    return render_template('gioi-thieu.html', instructors=instructors)

@app.route('/lien-he', methods=['GET','POST'])
def lien_he():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        email = request.form.get('email','').strip()
        message = request.form.get('message','').strip()
        if name and email and message:
            conn = get_db()
            conn.execute('INSERT INTO contacts (name,email,message) VALUES (?,?,?)', (name, email, message))
            conn.commit(); conn.close()
            return jsonify({'success': True, 'message': 'Cảm ơn bạn! Chúng tôi sẽ liên hệ sớm nhất.'})
        return jsonify({'success': False, 'message': 'Vui lòng điền đầy đủ thông tin.'})
    return render_template('lien-he.html')

#  AUTH ROUTES
@app.route('/login', methods=['POST'])
def login():
    email    = request.form.get('email','').strip()
    password = request.form.get('password','')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password'], password):
        session['user_id']  = user['id']
        session['user_name'] = user['name']
        return jsonify({'success': True, 'message': f'Chào mừng {user["name"]}!', 'is_admin': bool(user['is_admin'])})
    return jsonify({'success': False, 'message': 'Email hoặc mật khẩu không đúng.'})

@app.route('/register', methods=['POST'])
def register():
    name     = request.form.get('name','').strip()
    email    = request.form.get('email','').strip()
    password = request.form.get('password','')
    if not name or not email or not password:
        return jsonify({'success': False, 'message': 'Vui lòng điền đầy đủ thông tin.'})
    conn = get_db()
    if conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Email đã được sử dụng.'})
    conn.execute('INSERT INTO users (name,email,password) VALUES (?,?,?)', (name, email, generate_password_hash(password)))
    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    return jsonify({'success': True, 'message': f'Đăng ký thành công! Chào mừng {name}!'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('trang_chu'))

@app.route('/quen-mat-khau', methods=['GET','POST'])
def quen_mat_khau():
    if request.method == 'POST':
        step = request.form.get('step')
        conn = get_db()
        def parse_reset_expiry(raw_value):
            if not raw_value:
                return None
            try:
                return datetime.fromisoformat(str(raw_value).replace('Z', '+00:00'))
            except ValueError:
                return None
        if step == '1':
            email = request.form.get('email','').strip()
            if not conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
                conn.close(); return jsonify({'success': False, 'message': 'Email không tồn tại.'})
            token = secrets.token_hex(4).upper()
            conn.execute('INSERT INTO password_resets (email,token,expires_at) VALUES (?,?,?)',
                         (email, token, (datetime.now()+timedelta(minutes=15)).isoformat()))
            conn.commit(); conn.close()
            return jsonify({'success': True, 'message': f'Mã xác nhận (demo): {token}', 'token': token})
        elif step == '2':
            email = request.form.get('email','')
            token = request.form.get('token','').upper()
            reset = conn.execute('SELECT * FROM password_resets WHERE email=? AND token=? AND used=0 ORDER BY id DESC LIMIT 1', (email,token)).fetchone()
            if not reset:
                conn.close(); return jsonify({'success': False, 'message': 'Mã không đúng hoặc đã hết hạn.'})
            expires_at = parse_reset_expiry(reset['expires_at'])
            if not expires_at or expires_at < datetime.now():
                conn.close(); return jsonify({'success': False, 'message': 'Mã OTP đã hết hạn, vui lòng yêu cầu mã mới.'})
            conn.close()
            return jsonify({'success': True, 'message': 'Xác nhận OTP thành công. Vui lòng nhập mật khẩu mới.'})
        elif step == '3':
            email = request.form.get('email','')
            token = request.form.get('token','').upper()
            reset = conn.execute('SELECT * FROM password_resets WHERE email=? AND token=? AND used=0 ORDER BY id DESC LIMIT 1', (email,token)).fetchone()
            if not reset:
                conn.close(); return jsonify({'success': False, 'message': 'Mã OTP không hợp lệ hoặc đã được sử dụng.'})
            expires_at = parse_reset_expiry(reset['expires_at'])
            if not expires_at or expires_at < datetime.now():
                conn.close(); return jsonify({'success': False, 'message': 'Mã OTP đã hết hạn, vui lòng yêu cầu mã mới.'})
            new_pw = request.form.get('new_password','')
            if len(new_pw) < 6:
                conn.close(); return jsonify({'success': False, 'message': 'Mật khẩu tối thiểu 6 ký tự.'})
            conn.execute('UPDATE users SET password=? WHERE email=?', (generate_password_hash(new_pw), email))
            conn.execute('UPDATE password_resets SET used=1 WHERE id=?', (reset['id'],))
            conn.commit(); conn.close()
            return jsonify({'success': True, 'message': 'Đổi mật khẩu thành công!'})
        conn.close()
        return jsonify({'success': False, 'message': 'Bước xử lý không hợp lệ.'})
    return render_template('quen-mat-khau.html')

# =============================================================================
# USER ACCOUNT ROUTES
# Các route yêu cầu đăng nhập:
# - trang tài khoản, AI API, hồ sơ, học tập, ví, ngân hàng, xóa tài khoản
# =============================================================================
@app.route('/tai-khoan')
@login_required
def tai_khoan():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    enrolled_courses = conn.execute(
        'SELECT c.*, u.name as instructor_name, e.progress, e.enrolled_at, '
        'COALESCE('
        '  (SELECT l.id FROM lessons l WHERE l.course_id=c.id '
        '   AND l.id NOT IN (SELECT lp.lesson_id FROM lesson_progress lp WHERE lp.user_id=?) '
        '   ORDER BY l.order_num ASC LIMIT 1), '
        '  (SELECT l.id FROM lessons l WHERE l.course_id=c.id ORDER BY l.order_num ASC LIMIT 1)'
        ') as first_lesson_id '
        'FROM enrollments e JOIN courses c ON e.course_id=c.id '
        'LEFT JOIN users u ON c.instructor_id=u.id '
        'WHERE e.user_id=? ORDER BY e.enrolled_at DESC',
        (session['user_id'], session['user_id'])
    ).fetchall()
    created_courses = conn.execute(
        'SELECT c.*, cat.name as category_name, '
        '(SELECT COUNT(*) FROM enrollments WHERE course_id=c.id) as student_count, '
        'CASE WHEN c.instructor_id=? THEN 1 ELSE 0 END as is_owner '
        'FROM courses c '
        'LEFT JOIN categories cat ON c.category_id=cat.id '
        'LEFT JOIN course_teachers ct ON ct.course_id=c.id AND ct.teacher_id=? AND ct.status="active" '
        'WHERE c.instructor_id=? OR ct.id IS NOT NULL '
        'GROUP BY c.id '
        'ORDER BY c.created_at DESC',
        (session['user_id'], session['user_id'], session['user_id'])
    ).fetchall()
    wallet_txns = conn.execute(
        'SELECT * FROM wallet_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 20',
        (session['user_id'],)
    ).fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    recruit_overview = conn.execute(
        'SELECT c.id as course_id, c.title, '
        '(SELECT COUNT(*) FROM teacher_job_posts tj WHERE tj.course_id=c.id AND tj.status="open") as open_jobs, '
        '(SELECT COUNT(*) FROM teacher_applications ta '
        ' JOIN teacher_job_posts tj2 ON tj2.id=ta.job_post_id '
        ' WHERE tj2.course_id=c.id AND ta.status="pending") as pending_apps '
        'FROM courses c WHERE c.instructor_id=? ORDER BY c.created_at DESC',
        (session['user_id'],)
    ).fetchall()
    app_update_count = conn.execute(
        'SELECT COUNT(*) as n '
        'FROM teacher_applications a '
        'WHERE a.applicant_id=? '
        'AND a.reviewed_at IS NOT NULL '
        'AND datetime(a.reviewed_at) > datetime(COALESCE((SELECT last_seen_at FROM teacher_application_read_states WHERE user_id=?), "1970-01-01T00:00:00"))',
        (session['user_id'], session['user_id'])
    ).fetchone()['n']
    conn.close()
    ai_profile = generate_ai_personalization(session['user_id'])
    return render_template('tai-khoan-cua-toi.html', user=user,
                           enrolled_courses=enrolled_courses, created_courses=created_courses,
                           wallet_txns=wallet_txns, categories=categories,
                           ai_profile=ai_profile, recruit_overview=recruit_overview,
                           app_update_count=app_update_count)


@app.route('/api/ai/personalization')
@login_required
def api_ai_personalization():
    # Route realtime cho frontend tab AI (JS gọi định kỳ/manual refresh).
    profile = generate_ai_personalization(session['user_id'])
    return jsonify({'success': True, 'data': profile})

@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    name = request.form.get('name','').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Tên không được để trống.'})
    conn = get_db()
    conn.execute('UPDATE users SET name=? WHERE id=?', (name, session['user_id']))
    conn.commit(); conn.close()
    session['user_name'] = name
    return jsonify({'success': True, 'message': 'Cập nhật thành công!'})

@app.route('/enroll/<int:course_id>', methods=['POST'])
@login_required
def enroll(course_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    course = conn.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
    if not course:
        conn.close(); return jsonify({'success': False, 'message': 'Khóa học không tồn tại.'})
    # Không cho tự đăng ký khóa của mình
    if course['instructor_id'] == session['user_id']:
        conn.close(); return jsonify({'success': False, 'message': 'Bạn không thể đăng ký khóa học của chính mình!'})
    if conn.execute('SELECT id FROM enrollments WHERE user_id=? AND course_id=?', (session['user_id'], course_id)).fetchone():
        conn.close(); return jsonify({'success': False, 'message': 'Bạn đã đăng ký khóa học này rồi!'})
    # Kiểm tra ví
    price = course['price']
    if price > 0:
        if user['wallet_balance'] < price:
            conn.close(); return jsonify({'success': False, 'message': f'Số dư ví không đủ! Cần {price:,.0f}₫ nhưng bạn chỉ có {user["wallet_balance"]:,.0f}₫.'})
        conn.execute('UPDATE users SET wallet_balance=wallet_balance-? WHERE id=?', (price, session['user_id']))
        conn.execute('INSERT INTO wallet_transactions (user_id,type,amount,description) VALUES (?,?,?,?)',
                     (session['user_id'], 'purchase', price, f'Mua khóa học: {course["title"]}'))
    conn.execute('INSERT INTO enrollments (user_id,course_id) VALUES (?,?)', (session['user_id'], course_id))
    conn.execute('UPDATE courses SET total_students=total_students+1 WHERE id=?', (course_id,))
    conn.commit()
    first_lesson = conn.execute(
        'SELECT id FROM lessons WHERE course_id=? ORDER BY order_num, id LIMIT 1', (course_id,)
    ).fetchone()
    first_lesson_id = first_lesson['id'] if first_lesson else None
    conn.close()
    return jsonify({'success': True, 'message': f'Đăng ký khóa học thành công!', 'first_lesson_id': first_lesson_id})

# ── Tạo khóa học ──────────────────────────────────────────────────────
@app.route('/tao-khoa-hoc', methods=['POST'])
@login_required
def tao_khoa_hoc():
    d = request.form
    title = d.get('title','').strip()
    if not title:
        return jsonify({'success': False, 'message': 'Tên khóa học không được trống.'})
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') + '-' + secrets.token_hex(3)
    try:
        price = float((d.get('price', '') or '0').strip())
        original_price = float((d.get('original_price', '') or '0').strip())
        total_lessons = int((d.get('total_lessons', '') or '0').strip())
    except ValueError:
        return jsonify({'success': False, 'message': 'Giá học phí/giá gốc/số bài học không hợp lệ.'})
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO courses (title,slug,description,price,original_price,instructor_id,category_id,level,duration,total_lessons,is_featured) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (title, slug, d.get('description',''), price, original_price,
             session['user_id'], d.get('category_id') or None,
             d.get('level','beginner'), d.get('duration','0 giờ'),
             total_lessons, 0)
        )
        conn.commit(); conn.close()
        return jsonify({'success': True, 'message': f'Tạo khóa học "{title}" thành công!'})
    except Exception as e:
        conn.close(); return jsonify({'success': False, 'message': str(e)})

@app.route('/xoa-khoa-hoc/<int:cid>', methods=['POST'])
@login_required
def xoa_khoa_hoc(cid):
    conn = get_db()
    ensure_course_files_table(conn)
    course = conn.execute('SELECT * FROM courses WHERE id=? AND instructor_id=?', (cid, session['user_id'])).fetchone()
    if not course:
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền xóa khóa học này.'})
    conn.execute('DELETE FROM enrollments WHERE course_id=?', (cid,))
    # Xóa materials và exercises trước khi xóa lessons
    lesson_ids = [r['id'] for r in conn.execute('SELECT id FROM lessons WHERE course_id=?', (cid,)).fetchall()]
    for lid in lesson_ids:
        conn.execute('DELETE FROM lesson_materials WHERE lesson_id=?', (lid,))
        conn.execute('DELETE FROM lesson_exercises WHERE lesson_id=?', (lid,))
    conn.execute('DELETE FROM lesson_progress WHERE lesson_id IN (SELECT id FROM lessons WHERE course_id=?)', (cid,))
    conn.execute('DELETE FROM lessons WHERE course_id=?', (cid,))
    file_rows = conn.execute('SELECT file_url FROM course_files WHERE course_id=?', (cid,)).fetchall()
    for r in file_rows:
        file_url = r['file_url'] or ''
        if file_url.startswith('/static/'):
            rel_path = file_url[len('/static/'):].replace('/', os.sep)
            abs_path = os.path.join(app.static_folder, rel_path)
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except:
                    pass
    conn.execute('DELETE FROM course_files WHERE course_id=?', (cid,))
    conn.execute('DELETE FROM reviews WHERE course_id=?', (cid,))
    conn.execute('DELETE FROM courses WHERE id=?', (cid,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa khóa học!'})

@app.route('/wallet/clear-history', methods=['POST'])
@login_required
def clear_wallet_history():
    conn = get_db()
    conn.execute('DELETE FROM wallet_transactions WHERE user_id=?', (session['user_id'],))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa toàn bộ lịch sử giao dịch.'})


# ── Wallet ──────────────────────────────────────────────────────────
@app.route('/wallet/deposit', methods=['POST'])
@login_required
def wallet_deposit():
    # Route cũ đã bị thay bằng /wallet/deposit-request (cần admin duyệt)
    return jsonify({'success': False, 'message': 'Vui lòng sử dụng chức năng Gửi Yêu Cầu Nạp Tiền để được admin xác nhận.'})

@app.route('/wallet/withdraw', methods=['POST'])
@login_required
def wallet_withdraw():
    # Route cũ đã bị thay bằng /wallet/withdraw-request (cần admin duyệt)
    return jsonify({'success': False, 'message': 'Vui lòng sử dụng chức năng Gửi Yêu Cầu Rút Tiền để được admin xác nhận.'})

# ── Xem bài học ──────────────────────────────────────────────────────
@app.route('/xem-bai-hoc/<int:lesson_id>')
@login_required
def xem_bai_hoc(lesson_id):
    conn = get_db()
    lesson = conn.execute(
        'SELECT l.*, c.title as course_title, c.id as course_id, c.instructor_id '
        'FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not lesson:
        conn.close(); flash('Bài học không tồn tại.', 'error'); return redirect(url_for('tai_khoan'))
    # Kiểm tra quyền: đã đăng ký hoặc là giảng viên
    is_enrolled = conn.execute('SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
                               (session['user_id'], lesson['course_id'])).fetchone()
    is_instructor = lesson['instructor_id'] == session['user_id']
    # Cho phép xem bài học miễn phí (is_free) mà không cần đăng ký
    if not is_enrolled and not is_instructor and not lesson['is_free']:
        conn.close(); flash('Vui lòng đăng ký khóa học để xem bài học này.', 'warning'); return redirect(url_for('tat_ca_khoa_hoc'))
    materials = conn.execute('SELECT * FROM lesson_materials WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    exercises = conn.execute('SELECT * FROM lesson_exercises WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    all_lessons = conn.execute('SELECT * FROM lessons WHERE course_id=? ORDER BY order_num', (lesson['course_id'],)).fetchall()
    # completed lessons của user trong khóa này (chỉ lấy bài thuộc khóa đang xem)
    try:
        rows = conn.execute(
            'SELECT lp.lesson_id FROM lesson_progress lp '
            'JOIN lessons l ON lp.lesson_id=l.id '
            'WHERE lp.user_id=? AND l.course_id=?',
            (session['user_id'], lesson['course_id'])
        ).fetchall()
        completed_lessons = [r['lesson_id'] for r in rows]
    except Exception:
        completed_lessons = []
    conn.close()
    return render_template('xem-bai-hoc.html', lesson=lesson, materials=materials,
                           exercises=exercises, all_lessons=all_lessons,
                           is_instructor=is_instructor, completed_lessons=completed_lessons,
                           is_enrolled=bool(is_enrolled))

# ── Đánh dấu hoàn thành bài học ─────────────────────────────────────
@app.route('/mark-lesson-complete', methods=['POST'])
@login_required
def mark_lesson_complete():
    lesson_id = request.form.get('lesson_id', type=int)
    if not lesson_id:
        return jsonify({'success': False, 'message': 'Thiếu lesson_id.'})
    conn = get_db()
    try:
        lesson = conn.execute(
            'SELECT l.course_id FROM lessons l WHERE l.id=?', (lesson_id,)
        ).fetchone()
        if not lesson:
            conn.close(); return jsonify({'success': False, 'message': 'Bài học không tồn tại.'})
        # Kiểm tra user đã enroll khóa học này chưa
        is_enrolled = conn.execute(
            'SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
            (session['user_id'], lesson['course_id'])
        ).fetchone()
        # Cho phép instructor của khóa đó mark
        is_instructor = conn.execute(
            'SELECT instructor_id FROM courses WHERE id=?', (lesson['course_id'],)
        ).fetchone()
        if not is_enrolled and (not is_instructor or is_instructor['instructor_id'] != session['user_id']):
            conn.close(); return jsonify({'success': False, 'message': 'Bạn chưa đăng ký khóa học này.'})
        # Tạo bảng nếu chưa có
        conn.execute('''CREATE TABLE IF NOT EXISTS lesson_progress (
            user_id INTEGER, lesson_id INTEGER,
            completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, lesson_id))''')
        conn.execute('INSERT OR IGNORE INTO lesson_progress (user_id, lesson_id) VALUES (?,?)',
                     (session['user_id'], lesson_id))
        conn.commit()
        # Tính % tiến độ
        total   = conn.execute('SELECT COUNT(*) as n FROM lessons WHERE course_id=?',
                               (lesson['course_id'],)).fetchone()['n']
        done    = conn.execute(
            'SELECT COUNT(*) as n FROM lesson_progress lp '
            'JOIN lessons l ON lp.lesson_id=l.id '
            'WHERE lp.user_id=? AND l.course_id=?',
            (session['user_id'], lesson['course_id'])
        ).fetchone()['n']
        pct = round((done / total) * 100) if total else 0
        conn.close()
        return jsonify({'success': True, 'message': 'Đã đánh dấu hoàn thành!', 'progress_pct': pct})
    except Exception as e:
        conn.close(); return jsonify({'success': False, 'message': str(e)})


@app.route('/submit-lesson-quiz', methods=['POST'])
@login_required
def submit_lesson_quiz():
    """
    AI-in-learning endpoint:
    - Nhận đáp án bài tập của user trong 1 lesson
    - Chấm điểm + lưu lịch sử attempt
    - Trả về analytics cho lesson/course
    - Trả AI feedback tổng quan + AI mini feedback theo từng câu sai
    """
    lesson_id = request.form.get('lesson_id', type=int)
    answers_json = request.form.get('answers_json', '').strip()
    if not lesson_id or not answers_json:
        return jsonify({'success': False, 'message': 'Thiếu dữ liệu nộp bài.'})

    try:
        submitted_answers = json.loads(answers_json)
        if not isinstance(submitted_answers, dict):
            return jsonify({'success': False, 'message': 'Định dạng đáp án không hợp lệ.'})
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Không đọc được dữ liệu đáp án.'})

    conn = get_db()
    try:
        lesson = conn.execute(
            'SELECT l.id, l.is_free, l.course_id, c.instructor_id '
            'FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
            (lesson_id,)
        ).fetchone()
        if not lesson:
            conn.close(); return jsonify({'success': False, 'message': 'Bài học không tồn tại.'})

        is_enrolled = conn.execute(
            'SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
            (session['user_id'], lesson['course_id'])
        ).fetchone()
        is_instructor = lesson['instructor_id'] == session['user_id']
        if not is_enrolled and not is_instructor and not lesson['is_free']:
            conn.close(); return jsonify({'success': False, 'message': 'Bạn không có quyền nộp bài tập này.'})

        exercises = conn.execute(
            'SELECT id, question, correct_answer, option_a, option_b, option_c, option_d, explanation '
            'FROM lesson_exercises WHERE lesson_id=? ORDER BY order_num',
            (lesson_id,)
        ).fetchall()
        if not exercises:
            conn.close(); return jsonify({'success': False, 'message': 'Bài học chưa có câu hỏi.'})

        valid_ids = {str(ex['id']) for ex in exercises}
        normalized_answers = {str(k): str(v).upper().strip() for k, v in submitted_answers.items() if str(k) in valid_ids}

        total_questions = len(exercises)
        correct_count = 0
        wrong_questions = []
        wrong_details = []
        for ex in exercises:
            ex_id = str(ex['id'])
            chosen = normalized_answers.get(ex_id, '')
            correct = str(ex['correct_answer'] or '').upper().strip()
            if chosen and chosen == correct:
                correct_count += 1
            else:
                wrong_questions.append(ex['question'])
                # AI mini feedback for each wrong/missing answer.
                # Keep this short so frontend can render as small coaching cards.
                options = {
                    'A': ex['option_a'],
                    'B': ex['option_b'],
                    'C': ex['option_c'],
                    'D': ex['option_d'],
                }
                wrong_details.append({
                    'exercise_id': int(ex['id']),
                    'question': ex['question'],
                    'chosen': chosen or 'Chưa chọn',
                    'correct': correct or '-',
                    'correct_text': options.get(correct, '') or '',
                    'explanation': (ex['explanation'] or '').strip(),
                    'ai_tip': (
                        f"Xem lại trọng tâm của câu này, đáp án đúng là {correct}. "
                        f"Bạn nên ôn kỹ phần liên quan và thử làm lại ngay."
                    )
                })

        score_pct = round((correct_count / total_questions) * 100) if total_questions else 0
        passed = 1 if score_pct >= 60 else 0

        conn.execute('''CREATE TABLE IF NOT EXISTS lesson_quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            score_pct INTEGER NOT NULL,
            passed INTEGER DEFAULT 0,
            weak_points TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS lesson_progress (
            user_id INTEGER, lesson_id INTEGER,
            completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, lesson_id)
        )''')
        conn.execute(
            'INSERT INTO lesson_quiz_attempts (user_id, lesson_id, course_id, total_questions, correct_answers, score_pct, passed, weak_points) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (session['user_id'], lesson_id, lesson['course_id'], total_questions, correct_count, score_pct, passed,
             json.dumps(wrong_questions[:5], ensure_ascii=False))
        )

        # Tự động đánh dấu hoàn thành bài học nếu học viên đạt mốc 60%.
        # Mục tiêu: giảm thao tác tay cho user và đồng bộ tiến độ khóa học theo kết quả quiz.
        auto_marked_complete = False
        if passed:
            before_row = conn.execute(
                'SELECT COUNT(*) as n FROM lesson_progress WHERE user_id=? AND lesson_id=?',
                (session['user_id'], lesson_id)
            ).fetchone()
            before_done = int(before_row['n'] or 0)
            conn.execute(
                'INSERT OR IGNORE INTO lesson_progress (user_id, lesson_id) VALUES (?,?)',
                (session['user_id'], lesson_id)
            )
            after_row = conn.execute(
                'SELECT COUNT(*) as n FROM lesson_progress WHERE user_id=? AND lesson_id=?',
                (session['user_id'], lesson_id)
            ).fetchone()
            after_done = int(after_row['n'] or 0)
            auto_marked_complete = after_done > before_done
        conn.commit()

        lesson_stats = conn.execute(
            'SELECT COUNT(*) as attempts, MAX(score_pct) as best_score, AVG(score_pct) as avg_score '
            'FROM lesson_quiz_attempts WHERE user_id=? AND lesson_id=?',
            (session['user_id'], lesson_id)
        ).fetchone()
        # Lấy lịch sử điểm của lesson để vẽ chart tiến bộ (recent attempts).
        history_rows = conn.execute(
            'SELECT score_pct, created_at FROM lesson_quiz_attempts '
            'WHERE user_id=? AND lesson_id=? ORDER BY id DESC LIMIT 6',
            (session['user_id'], lesson_id)
        ).fetchall()
        # Đảo lại để frontend hiển thị theo thứ tự thời gian tăng dần.
        history_points = []
        for idx, row in enumerate(reversed(history_rows), start=1):
            history_points.append({
                'attempt_no': idx,
                'score_pct': int(row['score_pct'] or 0),
                'created_at': row['created_at']
            })

        course_stats = conn.execute(
            'SELECT AVG(t.score_pct) as course_accuracy '
            'FROM lesson_quiz_attempts t '
            'JOIN (SELECT lesson_id, MAX(id) as latest_id FROM lesson_quiz_attempts WHERE user_id=? AND course_id=? GROUP BY lesson_id) latest '
            'ON t.id = latest.latest_id',
            (session['user_id'], lesson['course_id'])
        ).fetchone()

        total_lessons = conn.execute(
            'SELECT COUNT(*) as n FROM lessons WHERE course_id=?',
            (lesson['course_id'],)
        ).fetchone()['n']
        completed_lessons = conn.execute(
            'SELECT COUNT(*) as n FROM lesson_progress lp JOIN lessons l ON lp.lesson_id=l.id '
            'WHERE lp.user_id=? AND l.course_id=?',
            (session['user_id'], lesson['course_id'])
        ).fetchone()['n']
        course_progress_pct = round((completed_lessons / total_lessons) * 100) if total_lessons else 0

        ai_feedback = (
            "Bạn làm rất tốt! Hãy chuyển sang bài tiếp theo để giữ nhịp học."
            if score_pct >= 85 else
            "Bạn đã đạt yêu cầu. Hãy ôn lại phần sai và làm lại để đạt mức cao hơn."
            if score_pct >= 60 else
            "Bạn chưa đạt mốc 60%. AI gợi ý: xem lại tài liệu bài này, tập trung vào các câu sai rồi làm lại ngay."
        )
        if wrong_questions:
            ai_feedback += f" Trọng tâm cần ôn: {wrong_questions[0][:90]}."

        # Kế hoạch 3 ngày ngắn gọn để người học hành động ngay sau khi nộp bài.
        # Trả về dạng list để frontend render thành checklist.
        if score_pct >= 85:
            study_plan_3d = [
                "Ngày 1: Ôn nhanh 1 lần các câu hỏi và ghi chú lại mẹo quan trọng.",
                "Ngày 2: Học tiếp bài kế tiếp trong khóa để giữ đà tiến bộ.",
                "Ngày 3: Làm lại quiz để hướng tới 100% và củng cố kiến thức.",
            ]
        elif score_pct >= 60:
            study_plan_3d = [
                "Ngày 1: Xem lại toàn bộ câu sai và đọc kỹ phần giải thích.",
                "Ngày 2: Ôn tài liệu bài học 20-30 phút, tập trung phần chưa chắc.",
                "Ngày 3: Làm lại quiz, mục tiêu tăng ít nhất 10% điểm.",
            ]
        else:
            study_plan_3d = [
                "Ngày 1: Đọc lại tài liệu từ đầu, tóm tắt 3 ý chính của bài.",
                "Ngày 2: Ôn kỹ các câu sai, tự giải thích vì sao đáp án đúng.",
                "Ngày 3: Làm lại quiz, mục tiêu đạt mốc 60% để mở rộng bài mới.",
            ]

        # Lưu lịch sử kế hoạch 3 ngày sau mỗi lần nộp bài để user theo dõi tiến trình học.
        conn.execute('''CREATE TABLE IF NOT EXISTS lesson_study_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            score_pct INTEGER NOT NULL,
            plan_json TEXT NOT NULL,
            progress_json TEXT DEFAULT "[]",
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Tương thích ngược: bổ sung cột progress_json cho DB cũ.
        try:
            conn.execute('ALTER TABLE lesson_study_plans ADD COLUMN progress_json TEXT DEFAULT "[]"')
        except Exception:
            pass
        initial_progress = [False] * max(1, min(3, len(study_plan_3d)))
        conn.execute(
            'INSERT INTO lesson_study_plans (user_id, lesson_id, course_id, score_pct, plan_json, progress_json) VALUES (?,?,?,?,?,?)',
            (
                session['user_id'],
                lesson_id,
                lesson['course_id'],
                score_pct,
                json.dumps(study_plan_3d, ensure_ascii=False),
                json.dumps(initial_progress, ensure_ascii=False)
            )
        )
        conn.commit()

        # Lấy lịch sử 3 kế hoạch gần nhất của lesson để hiển thị lại cho người học.
        plan_rows = conn.execute(
            'SELECT id, score_pct, plan_json, progress_json, created_at FROM lesson_study_plans '
            'WHERE user_id=? AND lesson_id=? ORDER BY id DESC LIMIT 3',
            (session['user_id'], lesson_id)
        ).fetchall()
        study_plan_history = []
        for row in plan_rows:
            try:
                plan_items = json.loads(row['plan_json'] or '[]')
                if not isinstance(plan_items, list):
                    plan_items = []
            except Exception:
                plan_items = []
            try:
                progress_items = json.loads(row['progress_json'] or '[]')
                if not isinstance(progress_items, list):
                    progress_items = []
            except Exception:
                progress_items = []
            if len(progress_items) < len(plan_items[:3]):
                progress_items = progress_items + [False] * (len(plan_items[:3]) - len(progress_items))
            progress_items = [bool(x) for x in progress_items[:3]]
            study_plan_history.append({
                'plan_id': int(row['id']),
                'score_pct': int(row['score_pct'] or 0),
                'created_at': row['created_at'],
                'items': plan_items[:3],
                'progress': progress_items
            })

        conn.close()
        return jsonify({
            'success': True,
            'data': {
                'score_pct': score_pct,
                'passed': bool(passed),
                'lesson_attempts': int(lesson_stats['attempts'] or 0),
                'lesson_best_score': int(lesson_stats['best_score'] or 0),
                'lesson_avg_score': round(float(lesson_stats['avg_score'] or 0), 1),
                'course_accuracy_pct': round(float(course_stats['course_accuracy'] or 0), 1),
                'course_progress_pct': course_progress_pct,
                'wrong_count': len(wrong_questions),
                'ai_feedback': ai_feedback,
                'wrong_details': wrong_details[:5],
                'history_points': history_points,
                'study_plan_3d': study_plan_3d,
                'auto_marked_complete': auto_marked_complete,
                'study_plan_history': study_plan_history
            }
        })
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/lesson-study-plan/mark-day', methods=['POST'])
@login_required
def mark_study_plan_day():
    """
    Cập nhật trạng thái hoàn thành 1 ngày trong kế hoạch 3 ngày.
    Input:
      - plan_id: id của bản ghi lesson_study_plans
      - day_index: 0..2
      - completed: "1"/"0"
    """
    plan_id = request.form.get('plan_id', type=int)
    day_index = request.form.get('day_index', type=int)
    completed_raw = (request.form.get('completed', '0') or '0').strip().lower()
    completed = completed_raw in ('1', 'true', 'yes', 'on')
    if not plan_id or day_index is None or day_index < 0 or day_index > 2:
        return jsonify({'success': False, 'message': 'Dữ liệu cập nhật không hợp lệ.'})

    conn = get_db()
    try:
        row = conn.execute(
            'SELECT id, user_id, plan_json, progress_json FROM lesson_study_plans WHERE id=?',
            (plan_id,)
        ).fetchone()
        if not row or int(row['user_id']) != int(session['user_id']):
            conn.close()
            return jsonify({'success': False, 'message': 'Không tìm thấy kế hoạch học tập.'})

        try:
            plan_items = json.loads(row['plan_json'] or '[]')
            if not isinstance(plan_items, list):
                plan_items = []
        except Exception:
            plan_items = []

        try:
            progress = json.loads(row['progress_json'] or '[]')
            if not isinstance(progress, list):
                progress = []
        except Exception:
            progress = []

        max_len = max(1, min(3, len(plan_items)))
        if len(progress) < max_len:
            progress = progress + [False] * (max_len - len(progress))
        progress = [bool(x) for x in progress[:max_len]]
        if day_index >= max_len:
            conn.close()
            return jsonify({'success': False, 'message': 'Ngày học không tồn tại trong kế hoạch.'})

        progress[day_index] = bool(completed)
        conn.execute(
            'UPDATE lesson_study_plans SET progress_json=? WHERE id=?',
            (json.dumps(progress, ensure_ascii=False), plan_id)
        )
        conn.commit()
        completed_count = sum(1 for x in progress if x)
        conn.close()
        return jsonify({
            'success': True,
            'message': 'Đã cập nhật tiến độ kế hoạch.',
            'data': {
                'plan_id': plan_id,
                'progress': progress,
                'completed_count': completed_count,
                'total_days': len(progress)
            }
        })
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'message': str(e)})

# ── Chỉnh sửa bài học (instructor) ─────────────────────────────────
@app.route('/chinh-sua-bai-hoc/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def chinh_sua_bai_hoc(lesson_id):
    conn = get_db()
    lesson = conn.execute(
        'SELECT l.*, c.title as course_title, c.instructor_id, c.id as course_id '
        'FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not lesson:
        conn.close(); flash('Bài học không tồn tại.', 'error')
        return redirect(url_for('tai_khoan'))
    if not can_manage_course(conn, lesson['course_id'], session['user_id']):
        conn.close(); flash('Bạn không có quyền chỉnh sửa bài học này.', 'error')
        return redirect(url_for('tai_khoan'))

    if request.method == 'POST':
        title    = request.form.get('title', '').strip()
        dur      = request.form.get('duration_minutes', type=int)
        order    = request.form.get('order_num', type=int) or 1
        video    = request.form.get('video_url', '').strip()
        is_free  = 1 if request.form.get('is_free') else 0
        if not title:
            conn.close(); return jsonify({'success': False, 'message': 'Tiêu đề không được trống.'})
        conn.execute(
            'UPDATE lessons SET title=?, duration_minutes=?, order_num=?, video_url=?, is_free=? WHERE id=?',
            (title, dur, order, video, is_free, lesson_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Đã lưu thông tin bài học!'})

    materials = conn.execute('SELECT * FROM lesson_materials WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    exercises = conn.execute('SELECT * FROM lesson_exercises WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    conn.close()
    return render_template('chinh-sua-bai-hoc.html', lesson=lesson, materials=materials, exercises=exercises)

# ── Chỉnh sửa khóa học (instructor) ────────────────────────────────
@app.route('/chinh-sua-khoa-hoc/<int:course_id>', methods=['GET'])
@login_required
def chinh_sua_khoa_hoc(course_id):
    conn = get_db()
    ensure_course_files_table(conn)
    image_col = get_course_image_column(conn)
    if image_col:
        course = conn.execute(
            f'SELECT *, {image_col} AS thumbnail FROM courses WHERE id=?',
            (course_id,)
        ).fetchone()
    else:
        course = conn.execute(
            'SELECT * FROM courses WHERE id=?',
            (course_id,)
        ).fetchone()
    if not course or not can_manage_course(conn, course_id, session['user_id']):
        conn.close(); flash('Không tìm thấy khóa học.', 'error')
        return redirect(url_for('tai_khoan'))
    lessons    = conn.execute('SELECT * FROM lessons WHERE course_id=? ORDER BY order_num', (course_id,)).fetchall()
    course_files = conn.execute('SELECT * FROM course_files WHERE course_id=? ORDER BY id DESC', (course_id,)).fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template(
        'chinh-sua-khoa-hoc.html',
        course=course,
        lessons=lessons,
        categories=categories,
        course_files=course_files
    )

# ── Cập nhật thông tin khóa học (instructor) ────────────────────────
@app.route('/cap-nhat-khoa-hoc/<int:course_id>', methods=['POST'])
@login_required
def cap_nhat_khoa_hoc(course_id):
    conn = get_db()
    image_col = get_course_image_column(conn)
    course = conn.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
    if not course or not can_manage_course(conn, course_id, session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền chỉnh sửa khóa học này.'})
    d = request.form
    title = d.get('title', '').strip()
    if not title:
        conn.close(); return jsonify({'success': False, 'message': 'Tên khóa học không được trống.'})
    try:
        price    = float(d.get('price', 0) or 0)
        ori_price = float(d.get('original_price', 0) or 0) if d.get('original_price', '').strip() else None
    except:
        conn.close(); return jsonify({'success': False, 'message': 'Giá không hợp lệ.'})
    # Xử lý ảnh bìa: ưu tiên file upload, nếu không thì dùng URL
    thumbnail = (course[image_col] if image_col else None)  # giữ nguyên nếu không có thay đổi
    uploaded_file = request.files.get('thumbnail_file')
    if uploaded_file and uploaded_file.filename:
        ext = os.path.splitext(secure_filename(uploaded_file.filename))[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            conn.close(); return jsonify({'success': False, 'message': 'Định dạng ảnh không hợp lệ (jpg, png, gif, webp).'})
        upload_dir = os.path.join(app.static_folder, 'images', 'courses')
        os.makedirs(upload_dir, exist_ok=True)
        fname = f"course_{course_id}_{secrets.token_hex(6)}{ext}"
        uploaded_file.save(os.path.join(upload_dir, fname))
        thumbnail = url_for('static', filename=f'images/courses/{fname}')
    else:
        url_input = d.get('thumbnail', '').strip()
        if url_input:
            thumbnail = url_input
    if image_col:
        conn.execute(
            f'UPDATE courses SET title=?, description=?, price=?, original_price=?, category_id=?, level=?, {image_col}=? WHERE id=?',
            (title, d.get('description',''), price, ori_price,
             d.get('category_id') or None, d.get('level','beginner'),
             thumbnail, course_id)
        )
    else:
        conn.execute(
            'UPDATE courses SET title=?, description=?, price=?, original_price=?, category_id=?, level=? WHERE id=?',
            (title, d.get('description',''), price, ori_price,
             d.get('category_id') or None, d.get('level','beginner'),
             course_id)
        )
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Đã cập nhật khóa học "{title}"!', 'thumbnail': thumbnail or ''})

@app.route('/them-file-khoa-hoc', methods=['POST'])
@login_required
def them_file_khoa_hoc():
    course_id = request.form.get('course_id', type=int)
    title = request.form.get('title', '').strip()
    uploaded_file = request.files.get('file')
    if not course_id or not uploaded_file or not uploaded_file.filename:
        return jsonify({'success': False, 'message': 'Vui lòng chọn file cần tải lên.'})
    conn = get_db()
    ensure_course_files_table(conn)
    course = conn.execute('SELECT id FROM courses WHERE id=?', (course_id,)).fetchone()
    if not course or not can_manage_course(conn, course_id, session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền thêm file cho khóa học này.'})
    safe_name = secure_filename(uploaded_file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    allowed = {'.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.zip', '.rar', '.txt'}
    if ext not in allowed:
        conn.close()
        return jsonify({'success': False, 'message': 'Định dạng file chưa hỗ trợ.'})
    upload_dir = os.path.join(app.static_folder, 'files', 'courses')
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"course_{course_id}_{secrets.token_hex(6)}{ext}"
    uploaded_file.save(os.path.join(upload_dir, stored_name))
    file_url = url_for('static', filename=f'files/courses/{stored_name}')
    file_title = title or safe_name
    cur = conn.execute(
        'INSERT INTO course_files (course_id, title, file_url, file_name) VALUES (?, ?, ?, ?)',
        (course_id, file_title, file_url, safe_name)
    )
    conn.commit()
    file_id = cur.lastrowid
    conn.close()
    return jsonify({
        'success': True,
        'message': 'Đã thêm file cho khóa học.',
        'file': {
            'id': file_id,
            'title': file_title,
            'file_url': file_url,
            'file_name': safe_name
        }
    })

@app.route('/xoa-file-khoa-hoc/<int:file_id>', methods=['POST'])
@login_required
def xoa_file_khoa_hoc(file_id):
    conn = get_db()
    ensure_course_files_table(conn)
    row = conn.execute(
        'SELECT cf.* FROM course_files cf WHERE cf.id=?',
        (file_id,)
    ).fetchone()
    if not row or not can_manage_course(conn, row['course_id'], session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không tìm thấy file hoặc không có quyền.'})
    file_url = row['file_url'] or ''
    if file_url.startswith('/static/'):
        rel_path = file_url[len('/static/'):].replace('/', os.sep)
        abs_path = os.path.join(app.static_folder, rel_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except:
                pass
    conn.execute('DELETE FROM course_files WHERE id=?', (file_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa file.'})

# ── Thêm bài học mới (instructor) ───────────────────────────────────
@app.route('/them-bai-hoc', methods=['POST'])
@login_required
def them_bai_hoc():
    course_id = request.form.get('course_id', type=int)
    title     = request.form.get('title', '').strip()
    if not course_id or not title:
        return jsonify({'success': False, 'message': 'Thiếu thông tin.'})
    conn = get_db()
    course = conn.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
    if not course or not can_manage_course(conn, course_id, session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    order    = request.form.get('order_num', type=int) or 1
    dur      = request.form.get('duration_minutes', type=int)
    video    = request.form.get('video_url', '').strip()
    is_free  = 1 if request.form.get('is_free') else 0
    cur = conn.execute(
        'INSERT INTO lessons (course_id, title, order_num, duration_minutes, video_url, is_free) VALUES (?,?,?,?,?,?)',
        (course_id, title, order, dur, video or None, is_free)
    )
    conn.execute('UPDATE courses SET total_lessons=(SELECT COUNT(*) FROM lessons WHERE course_id=?) WHERE id=?',
                 (course_id, course_id))
    conn.commit()
    lesson_id = cur.lastrowid
    conn.close()
    return jsonify({'success': True, 'message': 'Đã thêm bài học!', 'lesson_id': lesson_id})

# ── Xóa bài học (instructor) ─────────────────────────────────────────
@app.route('/xoa-bai-hoc/<int:lesson_id>', methods=['POST'])
@login_required
def xoa_bai_hoc(lesson_id):
    conn = get_db()
    lesson = conn.execute(
        'SELECT l.*, c.instructor_id, l.course_id FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not lesson or not can_manage_course(conn, lesson['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền xóa bài học này.'})
    course_id = lesson['course_id']
    conn.execute('DELETE FROM lesson_materials WHERE lesson_id=?', (lesson_id,))
    conn.execute('DELETE FROM lesson_exercises WHERE lesson_id=?', (lesson_id,))
    conn.execute('DELETE FROM lessons WHERE id=?', (lesson_id,))
    conn.execute('UPDATE courses SET total_lessons=(SELECT COUNT(*) FROM lessons WHERE course_id=?) WHERE id=?',
                 (course_id, course_id))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa bài học!'})

# ── Material CRUD ────────────────────────────────────────────────────
@app.route('/them-material', methods=['POST'])
@login_required
def them_material():
    lesson_id = request.form.get('lesson_id', type=int)
    title     = request.form.get('title', '').strip()
    mat_type  = request.form.get('material_type', 'document')
    content   = request.form.get('content', '')
    if not lesson_id or not title:
        return jsonify({'success': False, 'message': 'Thiếu thông tin.'})
    conn = get_db()
    # Verify ownership
    ok = conn.execute(
        'SELECT c.id as course_id FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    max_order = conn.execute('SELECT COALESCE(MAX(order_num),0)+1 as n FROM lesson_materials WHERE lesson_id=?',
                             (lesson_id,)).fetchone()['n']
    conn.execute('INSERT INTO lesson_materials (lesson_id, title, material_type, content, order_num) VALUES (?,?,?,?,?)',
                 (lesson_id, title, mat_type, content, max_order))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã thêm tài liệu!'})

@app.route('/chinh-sua-material/<int:mat_id>', methods=['POST'])
@login_required
def chinh_sua_material(mat_id):
    title    = request.form.get('title', '').strip()
    mat_type = request.form.get('material_type', 'document')
    content  = request.form.get('content', '')
    if not title:
        return jsonify({'success': False, 'message': 'Tiêu đề không được trống.'})
    conn = get_db()
    ok = conn.execute(
        'SELECT c.id as course_id FROM lesson_materials lm '
        'JOIN lessons l ON lm.lesson_id=l.id JOIN courses c ON l.course_id=c.id WHERE lm.id=?',
        (mat_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    conn.execute('UPDATE lesson_materials SET title=?, material_type=?, content=? WHERE id=?',
                 (title, mat_type, content, mat_id))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã lưu tài liệu!'})

@app.route('/xoa-material/<int:mat_id>', methods=['POST'])
@login_required
def xoa_material(mat_id):
    conn = get_db()
    ok = conn.execute(
        'SELECT c.id as course_id FROM lesson_materials lm '
        'JOIN lessons l ON lm.lesson_id=l.id JOIN courses c ON l.course_id=c.id WHERE lm.id=?',
        (mat_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    conn.execute('DELETE FROM lesson_materials WHERE id=?', (mat_id,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa tài liệu!'})

# ── Exercise CRUD ────────────────────────────────────────────────────
@app.route('/them-exercise', methods=['POST'])
@login_required
def them_exercise():
    lesson_id = request.form.get('lesson_id', type=int)
    question  = request.form.get('question', '').strip()
    correct   = request.form.get('correct_answer', '').strip().upper()
    if not lesson_id or not question or not correct:
        return jsonify({'success': False, 'message': 'Thiếu thông tin bắt buộc.'})
    conn = get_db()
    ok = conn.execute(
        'SELECT c.id as course_id FROM lessons l JOIN courses c ON l.course_id=c.id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    max_order = conn.execute('SELECT COALESCE(MAX(order_num),0)+1 as n FROM lesson_exercises WHERE lesson_id=?',
                             (lesson_id,)).fetchone()['n']
    conn.execute(
        'INSERT INTO lesson_exercises (lesson_id, question, option_a, option_b, option_c, option_d, correct_answer, explanation, order_num) VALUES (?,?,?,?,?,?,?,?,?)',
        (lesson_id, question,
         request.form.get('option_a',''), request.form.get('option_b',''),
         request.form.get('option_c',''), request.form.get('option_d',''),
         correct, request.form.get('explanation',''), max_order)
    )
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã thêm câu hỏi!'})

@app.route('/chinh-sua-exercise/<int:ex_id>', methods=['POST'])
@login_required
def chinh_sua_exercise(ex_id):
    question = request.form.get('question', '').strip()
    correct  = request.form.get('correct_answer', '').strip().upper()
    if not question or not correct:
        return jsonify({'success': False, 'message': 'Câu hỏi và đáp án đúng là bắt buộc.'})
    conn = get_db()
    ok = conn.execute(
        'SELECT c.id as course_id FROM lesson_exercises le '
        'JOIN lessons l ON le.lesson_id=l.id JOIN courses c ON l.course_id=c.id WHERE le.id=?',
        (ex_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    conn.execute(
        'UPDATE lesson_exercises SET question=?, option_a=?, option_b=?, option_c=?, option_d=?, correct_answer=?, explanation=? WHERE id=?',
        (question,
         request.form.get('option_a',''), request.form.get('option_b',''),
         request.form.get('option_c',''), request.form.get('option_d',''),
         correct, request.form.get('explanation',''), ex_id)
    )
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã lưu câu hỏi!'})

@app.route('/xoa-exercise/<int:ex_id>', methods=['POST'])
@login_required
def xoa_exercise(ex_id):
    conn = get_db()
    ok = conn.execute(
        'SELECT c.id as course_id FROM lesson_exercises le '
        'JOIN lessons l ON le.lesson_id=l.id JOIN courses c ON l.course_id=c.id WHERE le.id=?',
        (ex_id,)
    ).fetchone()
    if not ok or not can_manage_course(conn, ok['course_id'], session['user_id']):
        conn.close(); return jsonify({'success': False, 'message': 'Không có quyền.'})
    conn.execute('DELETE FROM lesson_exercises WHERE id=?', (ex_id,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa câu hỏi!'})



@app.route('/course-teacher-center/<int:course_id>')
@login_required
def course_teacher_center(course_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    if not is_course_owner(conn, course_id, session['user_id']):
        conn.close()
        flash('Bạn không có quyền quản lý tuyển giáo viên cho khóa học này.', 'error')
        return redirect(url_for('tai_khoan'))
    course = conn.execute('SELECT id, title FROM courses WHERE id=?', (course_id,)).fetchone()
    teachers = conn.execute(
        'SELECT ct.*, u.name, u.email FROM course_teachers ct '
        'JOIN users u ON u.id=ct.teacher_id WHERE ct.course_id=? ORDER BY ct.joined_at DESC',
        (course_id,)
    ).fetchall()
    invitations = conn.execute(
        'SELECT i.*, u.name as invited_name, u.email as invited_email '
        'FROM course_teacher_invitations i JOIN users u ON u.id=i.invited_user_id '
        'WHERE i.course_id=? ORDER BY i.created_at DESC',
        (course_id,)
    ).fetchall()
    jobs = conn.execute(
        'SELECT * FROM teacher_job_posts WHERE course_id=? ORDER BY created_at DESC',
        (course_id,)
    ).fetchall()
    applications = conn.execute(
        'SELECT a.*, u.name as applicant_name, u.email as applicant_email, j.title as job_title, '
        'GROUP_CONCAT(taa.file_type || ":" || taa.public_url, "||") as attachment_refs '
        'FROM teacher_applications a '
        'JOIN users u ON u.id=a.applicant_id '
        'JOIN teacher_job_posts j ON j.id=a.job_post_id '
        'LEFT JOIN teacher_application_attachments taa ON taa.application_id=a.id '
        'WHERE j.course_id=? '
        'GROUP BY a.id '
        'ORDER BY a.created_at DESC',
        (course_id,)
    ).fetchall()
    users = conn.execute(
        'SELECT id, name, email FROM users WHERE is_admin=0 AND id != ? ORDER BY name',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template(
        'teacher-center.html',
        course=course,
        teachers=teachers,
        invitations=invitations,
        jobs=jobs,
        applications=applications,
        users=users
    )


@app.route('/teacher-jobs')
def teacher_jobs_board():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    jobs = conn.execute(
        'SELECT j.*, c.title as course_title, c.id as course_id, u.name as owner_name '
        'FROM teacher_job_posts j '
        'JOIN courses c ON c.id=j.course_id '
        'JOIN users u ON u.id=j.created_by '
        'WHERE j.status="open" ORDER BY j.created_at DESC'
    ).fetchall()
    conn.close()
    return render_template('teacher-jobs-board.html', jobs=jobs)


@app.route('/teacher-jobs/<int:job_id>/apply', methods=['GET', 'POST'])
@login_required
def apply_teacher_job(job_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    job = conn.execute(
        'SELECT j.*, c.title as course_title, c.id as course_id, c.instructor_id '
        'FROM teacher_job_posts j JOIN courses c ON c.id=j.course_id WHERE j.id=?',
        (job_id,)
    ).fetchone()
    if not job:
        conn.close()
        flash('Tin tuyển không tồn tại.', 'error')
        return redirect(url_for('teacher_jobs_board'))
    if request.method == 'POST':
        if job['status'] != 'open':
            conn.close()
            return jsonify({'success': False, 'message': 'Tin tuyển đã đóng.'})
        if job['instructor_id'] == session['user_id']:
            conn.close()
            return jsonify({'success': False, 'message': 'Bạn không thể ứng tuyển khóa học do chính bạn tạo.'})
        if conn.execute(
            'SELECT id FROM teacher_applications WHERE job_post_id=? AND applicant_id=?',
            (job_id, session['user_id'])
        ).fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Bạn đã ứng tuyển tin này rồi.'})
        bio = request.form.get('bio', '').strip()
        exp = request.form.get('experience_summary', '').strip()
        contact_email = request.form.get('contact_email', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        if not bio or not contact_email:
            conn.close()
            return jsonify({'success': False, 'message': 'Vui lòng điền giới thiệu bản thân và email liên hệ.'})
        cur = conn.execute(
            'INSERT INTO teacher_applications (job_post_id, applicant_id, bio, experience_summary, contact_email, contact_phone) '
            'VALUES (?,?,?,?,?,?)',
            (job_id, session['user_id'], bio, exp, contact_email, contact_phone)
        )
        application_id = cur.lastrowid
        files = [
            ('cv_file', 'cv', {'.pdf', '.doc', '.docx'}),
            ('certificate_file', 'certificate', {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'}),
            ('avatar_file', 'avatar', {'.jpg', '.jpeg', '.png', '.webp'}),
        ]
        try:
            for field_name, file_type, allowed in files:
                f = request.files.get(field_name)
                if not f or not f.filename:
                    continue
                try:
                    uploaded = upload_service.upload_file(f, 'teacher-applications', allowed)
                except UploadServiceError as exc:
                    msg = str(exc)
                    # Demo-safe fallback: nếu chưa cấu hình cloud thì lưu local để không chặn nghiệp vụ.
                    if 'Thiếu cấu hình Cloudinary' in msg or 'Provider upload chưa được hỗ trợ' in msg:
                        uploaded = save_teacher_application_file_local(
                            f, application_id, file_type, allowed
                        )
                    else:
                        raise
                conn.execute(
                    'INSERT INTO teacher_application_attachments '
                    '(application_id, file_type, storage_provider, public_url, storage_key, mime_type, size_bytes) '
                    'VALUES (?,?,?,?,?,?,?)',
                    (
                        application_id,
                        file_type,
                        uploaded['provider'],
                        uploaded['public_url'],
                        uploaded['key'],
                        uploaded['mime_type'],
                        uploaded['size'],
                    )
                )
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': 'Ứng tuyển thành công! Chủ khóa học sẽ liên hệ sớm.'})
        except UploadServiceError as exc:
            conn.execute('DELETE FROM teacher_application_attachments WHERE application_id=?', (application_id,))
            conn.execute('DELETE FROM teacher_applications WHERE id=?', (application_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': False, 'message': str(exc)})
    my_application = conn.execute(
        'SELECT * FROM teacher_applications WHERE job_post_id=? AND applicant_id=?',
        (job_id, session['user_id'])
    ).fetchone()
    conn.close()
    return render_template('teacher-job-apply.html', job=job, my_application=my_application)


@app.route('/courses/<int:course_id>/teacher-invitations', methods=['POST'])
@login_required
def create_teacher_invitation(course_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    if not is_course_owner(conn, course_id, session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền thao tác.'})
    invited_user_id = request.form.get('invited_user_id', type=int)
    message = request.form.get('message', '').strip()
    if not invited_user_id:
        conn.close()
        return jsonify({'success': False, 'message': 'Vui lòng chọn giáo viên cần mời.'})
    if invited_user_id == session['user_id']:
        conn.close()
        return jsonify({'success': False, 'message': 'Bạn không thể tự mời chính mình.'})
    existing = conn.execute(
        'SELECT id FROM course_teacher_invitations WHERE course_id=? AND invited_user_id=? AND status="pending"',
        (course_id, invited_user_id)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Người này đã có lời mời đang chờ phản hồi.'})
    conn.execute(
        'INSERT INTO course_teacher_invitations (course_id, invited_user_id, invited_by, message, expires_at) '
        'VALUES (?,?,?,?,?)',
        (course_id, invited_user_id, session['user_id'], message, (datetime.now() + timedelta(days=14)).isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Đã gửi lời mời giáo viên.'})


@app.route('/teacher-invitations/<int:inv_id>/accept', methods=['POST'])
@login_required
def accept_teacher_invitation(inv_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    invitation = conn.execute(
        'SELECT * FROM course_teacher_invitations WHERE id=? AND invited_user_id=?',
        (inv_id, session['user_id'])
    ).fetchone()
    if not invitation:
        conn.close()
        return jsonify({'success': False, 'message': 'Không tìm thấy lời mời.'})
    if invitation['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'message': 'Lời mời đã được xử lý trước đó.'})
    conn.execute('UPDATE course_teacher_invitations SET status="accepted" WHERE id=?', (inv_id,))
    conn.execute(
        'INSERT OR IGNORE INTO course_teachers (course_id, teacher_id, role_in_course, status) VALUES (?,?,?,?)',
        (invitation['course_id'], session['user_id'], 'teacher', 'active')
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Bạn đã chấp nhận lời mời giảng dạy.'})


@app.route('/teacher-invitations/<int:inv_id>/reject', methods=['POST'])
@login_required
def reject_teacher_invitation(inv_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    invitation = conn.execute(
        'SELECT * FROM course_teacher_invitations WHERE id=? AND invited_user_id=?',
        (inv_id, session['user_id'])
    ).fetchone()
    if not invitation:
        conn.close()
        return jsonify({'success': False, 'message': 'Không tìm thấy lời mời.'})
    if invitation['status'] != 'pending':
        conn.close()
        return jsonify({'success': False, 'message': 'Lời mời đã được xử lý trước đó.'})
    conn.execute('UPDATE course_teacher_invitations SET status="rejected" WHERE id=?', (inv_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Bạn đã từ chối lời mời.'})


@app.route('/courses/<int:course_id>/teacher-jobs', methods=['POST'])
@login_required
def create_teacher_job(course_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    if not is_course_owner(conn, course_id, session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền tạo tin tuyển.'})
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    requirements = request.form.get('requirements', '').strip()
    deadline = request.form.get('deadline', '').strip() or None
    if not title or not description:
        conn.close()
        return jsonify({'success': False, 'message': 'Vui lòng nhập tiêu đề và mô tả.'})
    conn.execute(
        'INSERT INTO teacher_job_posts (course_id, title, description, requirements, deadline, created_by) '
        'VALUES (?,?,?,?,?,?)',
        (course_id, title, description, requirements, deadline, session['user_id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Đăng tin tuyển giáo viên thành công.'})


@app.route('/courses/<int:course_id>/teacher-jobs', methods=['GET'])
@login_required
def list_course_teacher_jobs(course_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    if not is_course_owner(conn, course_id, session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền xem tin tuyển.'}), 403
    rows = conn.execute(
        'SELECT * FROM teacher_job_posts WHERE course_id=? ORDER BY created_at DESC',
        (course_id,)
    ).fetchall()
    conn.close()
    return jsonify({'success': True, 'jobs': [dict(r) for r in rows]})


@app.route('/teacher-jobs/<int:job_id>', methods=['PATCH'])
@login_required
def patch_teacher_job(job_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    job = conn.execute('SELECT * FROM teacher_job_posts WHERE id=?', (job_id,)).fetchone()
    if not job or int(job['created_by']) != int(session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền cập nhật.'}), 403
    payload = request.get_json(silent=True) or {}
    status = (payload.get('status') or '').strip()
    if status not in ('open', 'closed'):
        conn.close()
        return jsonify({'success': False, 'message': 'Trạng thái không hợp lệ.'})
    conn.execute('UPDATE teacher_job_posts SET status=? WHERE id=?', (status, job_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Đã cập nhật trạng thái tin tuyển.'})


@app.route('/teacher-jobs/<int:job_id>/applications')
@login_required
def list_teacher_applications(job_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    job = conn.execute('SELECT * FROM teacher_job_posts WHERE id=?', (job_id,)).fetchone()
    if not job or int(job['created_by']) != int(session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền xem hồ sơ.'}), 403
    apps = conn.execute(
        'SELECT a.*, u.name as applicant_name FROM teacher_applications a '
        'JOIN users u ON u.id=a.applicant_id WHERE a.job_post_id=? ORDER BY a.created_at DESC',
        (job_id,)
    ).fetchall()
    data = []
    for app_row in apps:
        app_data = dict(app_row)
        att = conn.execute(
            'SELECT file_type, public_url FROM teacher_application_attachments WHERE application_id=?',
            (app_row['id'],)
        ).fetchall()
        app_data['attachments'] = [dict(a) for a in att]
        data.append(app_data)
    conn.close()
    return jsonify({'success': True, 'applications': data})


@app.route('/teacher-applications/<int:application_id>/status', methods=['PATCH', 'POST'])
@login_required
def update_teacher_application_status(application_id):
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    app_row = conn.execute(
        'SELECT a.*, j.course_id, j.created_by FROM teacher_applications a '
        'JOIN teacher_job_posts j ON j.id=a.job_post_id WHERE a.id=?',
        (application_id,)
    ).fetchone()
    if not app_row or int(app_row['created_by']) != int(session['user_id']):
        conn.close()
        return jsonify({'success': False, 'message': 'Không có quyền duyệt hồ sơ.'}), 403
    payload = request.get_json(silent=True) or {}
    status = (payload.get('status') or request.form.get('status') or '').strip()
    note = (payload.get('review_note') or request.form.get('review_note') or '').strip()
    if status not in ('pending', 'shortlisted', 'rejected', 'accepted'):
        conn.close()
        return jsonify({'success': False, 'message': 'Trạng thái không hợp lệ.'})
    conn.execute(
        'UPDATE teacher_applications SET status=?, review_note=?, reviewed_by=?, reviewed_at=? WHERE id=?',
        (status, note, session['user_id'], datetime.now().isoformat(), application_id)
    )
    if status == 'accepted':
        conn.execute(
            'INSERT OR IGNORE INTO course_teachers (course_id, teacher_id, role_in_course, status) VALUES (?,?,?,?)',
            (app_row['course_id'], app_row['applicant_id'], 'teacher', 'active')
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Đã cập nhật trạng thái hồ sơ.'})


@app.route('/my-teacher-invitations')
@login_required
def my_teacher_invitations():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    invitations = conn.execute(
        'SELECT i.*, c.title as course_title, u.name as owner_name '
        'FROM course_teacher_invitations i '
        'JOIN courses c ON c.id=i.course_id '
        'JOIN users u ON u.id=i.invited_by '
        'WHERE i.invited_user_id=? ORDER BY i.created_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template('teacher-invitations.html', invitations=invitations)


@app.route('/my-teacher-applications')
@login_required
def my_teacher_applications():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    applications = conn.execute(
        'SELECT a.*, j.title as job_title, c.title as course_title, u.name as owner_name '
        'FROM teacher_applications a '
        'JOIN teacher_job_posts j ON j.id=a.job_post_id '
        'JOIN courses c ON c.id=j.course_id '
        'JOIN users u ON u.id=j.created_by '
        'WHERE a.applicant_id=? ORDER BY a.created_at DESC',
        (session['user_id'],)
    ).fetchall()
    decorated = []
    for row in applications:
        app_data = dict(row)
        app_data['attachments'] = conn.execute(
            'SELECT file_type, public_url FROM teacher_application_attachments WHERE application_id=? ORDER BY id DESC',
            (row['id'],)
        ).fetchall()
        decorated.append(app_data)
    conn.execute(
        'INSERT INTO teacher_application_read_states (user_id, last_seen_at) VALUES (?, ?) '
        'ON CONFLICT(user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at',
        (session['user_id'], datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return render_template('teacher-applications-history.html', applications=decorated)


@app.route('/api/mobile/auth/login', methods=['POST'])
def api_mobile_login():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password'], password):
        return api_error('Email hoặc mật khẩu không đúng.', 'INVALID_CREDENTIALS', 401)
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    return api_ok({'user': {'id': user['id'], 'name': user['name'], 'email': user['email']}}, 'Đăng nhập thành công.')


@app.route('/api/mobile/auth/register', methods=['POST'])
def api_mobile_register():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    if not name or not email or not password:
        return api_error('Thiếu thông tin đăng ký.', 'VALIDATION_ERROR', 422)
    conn = get_db()
    if conn.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
        conn.close()
        return api_error('Email đã được sử dụng.', 'EMAIL_EXISTS', 409)
    conn.execute('INSERT INTO users (name,email,password) VALUES (?,?,?)', (name, email, generate_password_hash(password)))
    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    return api_ok({'user': {'id': user['id'], 'name': user['name'], 'email': user['email']}}, 'Đăng ký thành công.')


@app.route('/api/mobile/auth/me')
def api_mobile_me():
    if 'user_id' not in session:
        return api_error('Chưa đăng nhập.', 'UNAUTHORIZED', 401)
    conn = get_db()
    user = conn.execute('SELECT id, name, email FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    if not user:
        return api_error('Không tìm thấy người dùng.', 'USER_NOT_FOUND', 404)
    return api_ok({'user': dict(user)})


@app.route('/api/mobile/auth/logout', methods=['POST'])
def api_mobile_logout():
    session.clear()
    return api_ok({}, 'Đăng xuất thành công.')


@app.route('/api/mobile/courses')
@login_required
def api_mobile_courses():
    conn = get_db()
    rows = conn.execute(
        'SELECT c.*, u.name as instructor_name FROM courses c LEFT JOIN users u ON c.instructor_id=u.id ORDER BY c.id DESC'
    ).fetchall()
    conn.close()
    return api_ok({'courses': [dict(r) for r in rows]})


@app.route('/api/mobile/courses/<int:course_id>')
@login_required
def api_mobile_course_detail(course_id):
    conn = get_db()
    course = conn.execute(
        'SELECT c.*, u.name as instructor_name FROM courses c LEFT JOIN users u ON c.instructor_id=u.id WHERE c.id=?',
        (course_id,)
    ).fetchone()
    if not course:
        conn.close()
        return api_error('Khóa học không tồn tại.', 'COURSE_NOT_FOUND', 404)
    lessons = conn.execute('SELECT * FROM lessons WHERE course_id=? ORDER BY order_num', (course_id,)).fetchall()
    conn.close()
    return api_ok({'course': dict(course), 'lessons': [dict(l) for l in lessons]})


@app.route('/api/mobile/courses/<int:course_id>/enroll', methods=['POST'])
@login_required
def api_mobile_enroll(course_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    course = conn.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
    if not course:
        conn.close()
        return api_error('Khóa học không tồn tại.', 'COURSE_NOT_FOUND', 404)
    if course['instructor_id'] == session['user_id']:
        conn.close()
        return api_error('Bạn không thể đăng ký khóa học của chính mình.', 'SELF_ENROLL_FORBIDDEN', 403)
    if conn.execute('SELECT id FROM enrollments WHERE user_id=? AND course_id=?', (session['user_id'], course_id)).fetchone():
        conn.close()
        return api_error('Bạn đã đăng ký khóa học này rồi.', 'ALREADY_ENROLLED', 409)
    price = course['price']
    if price > 0 and user['wallet_balance'] < price:
        conn.close()
        return api_error('Số dư ví không đủ.', 'INSUFFICIENT_BALANCE', 422)
    if price > 0:
        conn.execute('UPDATE users SET wallet_balance=wallet_balance-? WHERE id=?', (price, session['user_id']))
        conn.execute(
            'INSERT INTO wallet_transactions (user_id,type,amount,description) VALUES (?,?,?,?)',
            (session['user_id'], 'purchase', price, f'Mua khóa học: {course["title"]}')
        )
    conn.execute('INSERT INTO enrollments (user_id,course_id) VALUES (?,?)', (session['user_id'], course_id))
    conn.execute('UPDATE courses SET total_students=total_students+1 WHERE id=?', (course_id,))
    conn.commit()
    first_lesson = conn.execute('SELECT id FROM lessons WHERE course_id=? ORDER BY order_num, id LIMIT 1', (course_id,)).fetchone()
    conn.close()
    return api_ok({'first_lesson_id': first_lesson['id'] if first_lesson else None}, 'Đăng ký khóa học thành công.')


@app.route('/api/mobile/lessons/<int:lesson_id>')
@login_required
def api_mobile_lesson_detail(lesson_id):
    conn = get_db()
    lesson = conn.execute(
        'SELECT l.*, c.instructor_id FROM lessons l JOIN courses c ON c.id=l.course_id WHERE l.id=?',
        (lesson_id,)
    ).fetchone()
    if not lesson:
        conn.close()
        return api_error('Bài học không tồn tại.', 'LESSON_NOT_FOUND', 404)
    is_enrolled = conn.execute(
        'SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
        (session['user_id'], lesson['course_id'])
    ).fetchone()
    if not is_enrolled and int(lesson['instructor_id']) != int(session['user_id']) and not lesson['is_free']:
        conn.close()
        return api_error('Bạn không có quyền xem bài học này.', 'FORBIDDEN', 403)
    materials = conn.execute('SELECT * FROM lesson_materials WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    exercises = conn.execute('SELECT * FROM lesson_exercises WHERE lesson_id=? ORDER BY order_num', (lesson_id,)).fetchall()
    all_lessons = conn.execute('SELECT * FROM lessons WHERE course_id=? ORDER BY order_num', (lesson['course_id'],)).fetchall()
    conn.close()
    return api_ok({
        'lesson': dict(lesson),
        'materials': [dict(m) for m in materials],
        'exercises': [dict(e) for e in exercises],
        'all_lessons': [dict(l) for l in all_lessons]
    })


@app.route('/api/mobile/teacher-jobs')
@login_required
def api_mobile_teacher_jobs():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    jobs = conn.execute(
        'SELECT j.*, c.title as course_title, u.name as owner_name '
        'FROM teacher_job_posts j '
        'JOIN courses c ON c.id=j.course_id '
        'JOIN users u ON u.id=j.created_by '
        'WHERE j.status="open" ORDER BY j.created_at DESC'
    ).fetchall()
    conn.close()
    return api_ok({'jobs': [dict(j) for j in jobs]})


@app.route('/api/mobile/my-teacher-applications')
@login_required
def api_mobile_my_teacher_applications():
    conn = get_db()
    ensure_teacher_recruitment_tables(conn)
    applications = conn.execute(
        'SELECT a.id, a.status, a.review_note, a.created_at, a.reviewed_at, '
        'j.title as job_title, c.title as course_title, u.name as owner_name '
        'FROM teacher_applications a '
        'JOIN teacher_job_posts j ON j.id=a.job_post_id '
        'JOIN courses c ON c.id=j.course_id '
        'JOIN users u ON u.id=j.created_by '
        'WHERE a.applicant_id=? ORDER BY a.created_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return api_ok({'applications': [dict(a) for a in applications]})


@app.route('/api/mobile/ai-profile')
@login_required
def api_mobile_ai_profile():
    profile = generate_ai_personalization(session['user_id'])
    return api_ok({'profile': profile})


@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    # Luôn làm sạch session khi vào trang admin login để hỗ trợ đổi tài khoản.
    if request.method == 'GET':
        session.clear()
    if request.method == 'POST':
        email = request.form.get('email','')
        password = request.form.get('password','')
        conn = get_db()
        user_any = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        user = conn.execute('SELECT * FROM users WHERE email=? AND is_admin=1', (email,)).fetchone()
        conn.close()
        if user_any and not user:
            flash('Tài khoản này không có quyền quản trị.', 'error')
            return render_template('admin/login.html')
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('admin_dashboard'))
        flash('Sai thông tin đăng nhập.', 'error')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    total_users   = conn.execute('SELECT COUNT(*) FROM users WHERE is_admin=0').fetchone()[0]
    total_courses = conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0]
    total_enrolls = conn.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0]
    total_revenue = conn.execute('SELECT COALESCE(SUM(c.price),0) FROM enrollments e JOIN courses c ON e.course_id=c.id').fetchone()[0]
    new_users_week = conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin=0 AND created_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    stats = {
        'users':          total_users,
        'courses':        total_courses,
        'enrolls':        total_enrolls,
        'contacts':       conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],
        'total_users':    total_users,
        'total_courses':  total_courses,
        'total_enrolls':  total_enrolls,
        'total_revenue':  total_revenue,
        'new_users_week': new_users_week,
    }
    recent_enrolls = conn.execute(
        'SELECT e.*, u.name as user_name, u.email as user_email, c.title as course_title, c.price as price '
        'FROM enrollments e JOIN users u ON e.user_id=u.id JOIN courses c ON e.course_id=c.id '
        'ORDER BY e.enrolled_at DESC LIMIT 10'
    ).fetchall()
    top_courses = conn.execute(
        'SELECT c.*, cat.name as category_name, u.name as instructor_name '
        'FROM courses c LEFT JOIN categories cat ON c.category_id=cat.id '
        'LEFT JOIN users u ON c.instructor_id=u.id ORDER BY c.total_students DESC LIMIT 5'
    ).fetchall()
    monthly = conn.execute(
        "SELECT strftime('%Y-%m',enrolled_at) as month, COUNT(*) as count "
        "FROM enrollments GROUP BY month ORDER BY month DESC LIMIT 6"
    ).fetchall()
    conn.close()
    return render_template('admin/dashboard.html', stats=stats, recent_enrolls=recent_enrolls,
                           top_courses=top_courses, monthly=list(reversed(monthly)))

@app.route('/admin/courses')
@admin_required
def admin_courses():
    q       = request.args.get('q','')
    page    = int(request.args.get('page',1))
    per_page = 10
    conn    = get_db()
    base    = ('SELECT c.*, cat.name as category_name, u.name as instructor_name '
               'FROM courses c LEFT JOIN categories cat ON c.category_id=cat.id '
               'LEFT JOIN users u ON c.instructor_id=u.id WHERE 1=1')
    params  = []
    if q: base += ' AND c.title LIKE ?'; params.append(f'%{q}%')
    total   = conn.execute(f'SELECT COUNT(*) FROM ({base})', params).fetchone()[0]
    courses = conn.execute(base+f' ORDER BY c.id DESC LIMIT {per_page} OFFSET {(page-1)*per_page}', params).fetchall()
    categories  = conn.execute('SELECT * FROM categories').fetchall()
    instructors = conn.execute('SELECT id,name FROM users WHERE is_admin=0').fetchall()
    conn.close()
    return render_template('admin/courses.html', courses=courses, categories=categories,
                           instructors=instructors, total=total, page=page,
                           total_pages=(total+per_page-1)//per_page, q=q)

@app.route('/admin/courses/get/<int:cid>')
@admin_required
def admin_get_course(cid):
    conn = get_db()
    c = conn.execute('SELECT * FROM courses WHERE id=?',(cid,)).fetchone()
    conn.close()
    return jsonify(dict(c)) if c else (jsonify({'error':'Not found'}),404)

@app.route('/admin/courses/add', methods=['POST'])
@admin_required
def admin_add_course():
    d = request.form
    title = d.get('title','').strip()
    if not title: return jsonify({'success':False,'message':'Tên khóa học không được trống.'})
    slug = re.sub(r'[^a-z0-9]+','-', title.lower()).strip('-') + '-' + secrets.token_hex(2)
    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO courses (title,slug,description,price,original_price,instructor_id,category_id,level,duration,total_lessons,is_featured) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (title, slug, d.get('description',''), float(d.get('price',0)), float(d.get('original_price',0)),
             d.get('instructor_id') or None, d.get('category_id') or None,
             d.get('level','beginner'), d.get('duration','0 giờ'),
             int(d.get('total_lessons',0)), int(d.get('is_featured',0)))
        )
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':f'Đã thêm khóa học "{title}"!'})
    except Exception as e:
        conn.close(); return jsonify({'success':False,'message':str(e)})

@app.route('/admin/courses/edit/<int:cid>', methods=['POST'])
@admin_required
def admin_edit_course(cid):
    d = request.form
    conn = get_db()
    try:
        conn.execute(
            'UPDATE courses SET title=?,description=?,price=?,original_price=?,instructor_id=?,category_id=?,level=?,duration=?,total_lessons=?,is_featured=? WHERE id=?',
            (d.get('title'), d.get('description',''), float(d.get('price',0)), float(d.get('original_price',0)),
             d.get('instructor_id') or None, d.get('category_id') or None,
             d.get('level','beginner'), d.get('duration','0 giờ'),
             int(d.get('total_lessons',0)), int(d.get('is_featured',0)), cid)
        )
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':'Cập nhật khóa học thành công!'})
    except Exception as e:
        conn.close(); return jsonify({'success':False,'message':str(e)})

@app.route('/admin/courses/delete/<int:cid>', methods=['POST'])
@admin_required
def admin_delete_course(cid):
    conn = get_db()
    conn.execute('DELETE FROM enrollments WHERE course_id=?',(cid,))
    lesson_ids = [r['id'] for r in conn.execute('SELECT id FROM lessons WHERE course_id=?', (cid,)).fetchall()]
    for lid in lesson_ids:
        conn.execute('DELETE FROM lesson_materials WHERE lesson_id=?', (lid,))
        conn.execute('DELETE FROM lesson_exercises WHERE lesson_id=?', (lid,))
    conn.execute('DELETE FROM lesson_progress WHERE lesson_id IN (SELECT id FROM lessons WHERE course_id=?)', (cid,))
    conn.execute('DELETE FROM lessons WHERE course_id=?',(cid,))
    conn.execute('DELETE FROM reviews WHERE course_id=?',(cid,))
    conn.execute('DELETE FROM courses WHERE id=?',(cid,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Đã xóa khóa học!'})

@app.route('/admin/courses/lock/<int:cid>', methods=['POST'])
@admin_required
def admin_lock_course(cid):
    locked = int(request.form.get('locked', 1))
    conn = get_db()
    try:
        conn.execute('ALTER TABLE courses ADD COLUMN is_locked INTEGER DEFAULT 0')
        conn.commit()
    except: pass
    conn.execute('UPDATE courses SET is_locked=? WHERE id=?', (locked, cid))
    conn.commit(); conn.close()
    msg = 'Đã khóa khóa học!' if locked else 'Đã mở khóa khóa học!'
    return jsonify({'success': True, 'message': msg})

@app.route('/admin/users')
@admin_required
def admin_users():
    q       = request.args.get('q','')
    page    = int(request.args.get('page',1))
    per_page = 12
    conn    = get_db()
    base    = 'SELECT u.*, COUNT(e.id) as enroll_count FROM users u LEFT JOIN enrollments e ON u.id=e.user_id WHERE u.is_admin=0'
    params  = []
    if q: base += ' AND (u.name LIKE ? OR u.email LIKE ?)'; params.extend([f'%{q}%',f'%{q}%'])
    base   += ' GROUP BY u.id'
    total   = conn.execute(f'SELECT COUNT(*) FROM ({base})',params).fetchone()[0]
    users   = conn.execute(base+f' ORDER BY u.id DESC LIMIT {per_page} OFFSET {(page-1)*per_page}',params).fetchall()
    conn.close()
    return render_template('admin/users.html', users=users, total=total, page=page,
                           total_pages=(total+per_page-1)//per_page, q=q)

@app.route('/admin/users/get/<int:uid>')
@admin_required
def admin_get_user(uid):
    conn = get_db()
    user   = conn.execute('SELECT id,name,email,created_at FROM users WHERE id=?',(uid,)).fetchone()
    enrolls= conn.execute('SELECT c.title,e.enrolled_at,e.progress FROM enrollments e JOIN courses c ON e.course_id=c.id WHERE e.user_id=?',(uid,)).fetchall()
    conn.close()
    return jsonify({'user':dict(user),'enrollments':[dict(e) for e in enrolls]}) if user else (jsonify({'error':'Not found'}),404)

@app.route('/admin/users/delete/<int:uid>', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    conn = get_db()
    conn.execute('DELETE FROM enrollments WHERE user_id=?',(uid,))
    conn.execute('DELETE FROM reviews WHERE user_id=?',(uid,))
    conn.execute('DELETE FROM users WHERE id=? AND is_admin=0',(uid,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Đã xóa học viên!'})

@app.route('/admin/contacts')
@admin_required
def admin_contacts():
    page    = int(request.args.get('page',1))
    per_page = 15
    conn    = get_db()
    total   = conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
    contacts= conn.execute('SELECT * FROM contacts ORDER BY created_at DESC LIMIT ? OFFSET ?',
                           (per_page,(page-1)*per_page)).fetchall()
    conn.close()
    return render_template('admin/contacts.html', contacts=contacts, total=total,
                           page=page, total_pages=(total+per_page-1)//per_page)

@app.route('/admin/contacts/delete/<int:cid>', methods=['POST'])
@admin_required
def admin_delete_contact(cid):
    conn = get_db()
    conn.execute('DELETE FROM contacts WHERE id=?',(cid,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Đã xóa liên hệ!'})

@app.route('/admin/categories')
@admin_required
def admin_categories():
    conn = get_db()
    cats = conn.execute('SELECT cat.*, COUNT(c.id) as course_count FROM categories cat LEFT JOIN courses c ON cat.id=c.category_id GROUP BY cat.id ORDER BY cat.id').fetchall()
    conn.close()
    return render_template('admin/categories.html', categories=cats)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def admin_add_category():
    name = request.form.get('name','').strip()
    if not name: return jsonify({'success':False,'message':'Tên danh mục không được trống.'})
    slug = re.sub(r'[^a-z0-9]+','-', name.lower()).strip('-')
    conn = get_db()
    try:
        conn.execute('INSERT INTO categories (name,slug) VALUES (?,?)',(name,slug))
        conn.commit(); conn.close()
        return jsonify({'success':True,'message':f'Đã thêm danh mục "{name}"!'})
    except:
        conn.close(); return jsonify({'success':False,'message':'Tên hoặc slug đã tồn tại.'})

@app.route('/admin/categories/edit/<int:cid>', methods=['POST'])
@admin_required
def admin_edit_category(cid):
    name = request.form.get('name','').strip()
    if not name: return jsonify({'success':False,'message':'Tên không được trống.'})
    conn = get_db()
    conn.execute('UPDATE categories SET name=? WHERE id=?',(name,cid))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Đã cập nhật danh mục!'})

@app.route('/admin/categories/delete/<int:cid>', methods=['POST'])
@admin_required
def admin_delete_category(cid):
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM courses WHERE category_id=?',(cid,)).fetchone()[0]
    if count:
        conn.close(); return jsonify({'success':False,'message':f'Không thể xóa! Có {count} khóa học đang dùng.'})
    conn.execute('DELETE FROM categories WHERE id=?',(cid,))
    conn.commit(); conn.close()
    return jsonify({'success':True,'message':'Đã xóa danh mục!'})

# ── Bank Info ──────────────────────────────────────────────────────────
@app.route('/update-bank-info', methods=['POST'])
@login_required
def update_bank_info():
    bank_name    = request.form.get('bank_name','').strip()
    bank_account = request.form.get('bank_account','').strip()
    bank_holder  = request.form.get('bank_holder','').strip()
    if not bank_name or not bank_account or not bank_holder:
        return jsonify({'success': False, 'message': 'Vui lòng điền đầy đủ thông tin ngân hàng.'})
    conn = get_db()
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_name TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_account TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_holder TEXT DEFAULT ""'); conn.commit()
    except: pass
    # Kiểm tra trùng số tài khoản ngân hàng với tài khoản khác
    existing = conn.execute(
        'SELECT id FROM users WHERE bank_account=? AND id!=?',
        (bank_account, session['user_id'])
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Số tài khoản ngân hàng này đã được đăng ký bởi tài khoản khác. Vui lòng kiểm tra lại.'})
    conn.execute('UPDATE users SET bank_name=?, bank_account=?, bank_holder=? WHERE id=?',
                 (bank_name, bank_account, bank_holder, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Cập nhật thông tin ngân hàng thành công!'})

# ── Delete Account Request ─────────────────────────────────────────────
@app.route('/request-delete-account', methods=['POST'])
@login_required
def request_delete_account():
    reason = request.form.get('reason','').strip()
    if not reason:
        return jsonify({'success': False, 'message': 'Vui lòng nhập lý do xóa tài khoản.'})
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS delete_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT "pending",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    existing = conn.execute('SELECT id FROM delete_requests WHERE user_id=? AND status="pending"', (session['user_id'],)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'message': 'Bạn đã có yêu cầu xóa tài khoản đang chờ xử lý.'})
    conn.execute('INSERT INTO delete_requests (user_id, reason) VALUES (?,?)', (session['user_id'], reason))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Yêu cầu xóa tài khoản đã được gửi! Admin sẽ xử lý sớm nhất.'})

# ── Withdraw Request (pending → admin approves/rejects) ────────────────
@app.route('/wallet/withdraw-request', methods=['POST'])
@login_required
def wallet_withdraw_request():
    try:
        amount = float(request.form.get('amount', 0))
    except:
        return jsonify({'success': False, 'message': 'Số tiền không hợp lệ.'})
    if amount < 100000:
        return jsonify({'success': False, 'message': 'Số tiền rút tối thiểu là 100.000₫.'})
    conn = get_db()
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_name TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_account TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_holder TEXT DEFAULT ""'); conn.commit()
    except: pass
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if user['wallet_balance'] < amount:
        conn.close(); return jsonify({'success': False, 'message': 'Số dư không đủ!'})
    bank_account = user['bank_account'] if user['bank_account'] else ''
    if not bank_account:
        conn.close(); return jsonify({'success': False, 'message': 'Vui lòng cập nhật thông tin ngân hàng trước khi rút tiền.'})
    conn.execute('UPDATE users SET wallet_balance=wallet_balance-? WHERE id=?', (amount, session['user_id']))
    conn.execute('INSERT INTO wallet_transactions (user_id,type,amount,description,status) VALUES (?,?,?,?,?)',
                 (session['user_id'], 'withdraw', amount,
                  f'Rút tiền về TK {user["bank_account"]} ({user["bank_name"]})', 'pending'))
    conn.commit()
    new_balance = conn.execute('SELECT wallet_balance FROM users WHERE id=?', (session['user_id'],)).fetchone()['wallet_balance']
    conn.close()
    return jsonify({'success': True,
                    'message': 'Yêu cầu rút tiền đã được gửi! Admin sẽ chuyển khoản trong 1-3 ngày làm việc.',
                    'new_balance': new_balance})

# ── Admin: Withdrawal Requests -----------------------------------------
# complete  -> xác nhận chuyển khoản thành công
# reject    -> trả tiền lại ví + ghi transaction refund
@app.route('/admin/withdrawals')
@admin_required
def admin_withdrawals():
    page     = int(request.args.get('page', 1))
    per_page = 15
    conn     = get_db()
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_name TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_account TEXT DEFAULT ""'); conn.commit()
    except: pass
    try:
        conn.execute('ALTER TABLE users ADD COLUMN bank_holder TEXT DEFAULT ""'); conn.commit()
    except: pass
    total    = conn.execute("SELECT COUNT(*) FROM wallet_transactions WHERE type='withdraw'").fetchone()[0]
    requests = conn.execute(
        '''SELECT wt.*, u.name as user_name, u.email as user_email,
                  u.bank_name, u.bank_account, u.bank_holder
           FROM wallet_transactions wt
           JOIN users u ON wt.user_id=u.id
           WHERE wt.type='withdraw'
           ORDER BY wt.created_at DESC
           LIMIT ? OFFSET ?''',
        (per_page, (page-1)*per_page)
    ).fetchall()
    conn.close()
    return render_template('admin/withdrawals.html', requests=requests, total=total,
                           page=page, total_pages=(total+per_page-1)//per_page)

@app.route('/admin/withdrawals/complete/<int:wid>', methods=['POST'])
@admin_required
def admin_complete_withdrawal(wid):
    conn = get_db()
    txn = conn.execute('SELECT * FROM wallet_transactions WHERE id=? AND type="withdraw"', (wid,)).fetchone()
    if not txn:
        conn.close(); return jsonify({'success': False, 'message': 'Không tìm thấy yêu cầu.'})
    if txn['status'] != 'pending':
        conn.close(); return jsonify({'success': False, 'message': 'Yêu cầu này không còn ở trạng thái chờ xử lý.'})
    conn.execute('UPDATE wallet_transactions SET status="completed" WHERE id=?', (wid,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã đánh dấu hoàn thành!'})


@app.route('/admin/withdrawals/reject/<int:wid>', methods=['POST'])
@admin_required
def admin_reject_withdrawal(wid):
    note = request.form.get('note', '').strip()
    conn = get_db()
    txn = conn.execute('SELECT * FROM wallet_transactions WHERE id=? AND type="withdraw"', (wid,)).fetchone()
    if not txn:
        conn.close(); return jsonify({'success': False, 'message': 'Không tìm thấy yêu cầu.'})
    if txn['status'] != 'pending':
        conn.close(); return jsonify({'success': False, 'message': 'Yêu cầu này không còn ở trạng thái chờ xử lý.'})
    uid = txn['user_id']
    amount = float(txn['amount'])
    conn.execute('UPDATE users SET wallet_balance=wallet_balance+? WHERE id=?', (amount, uid))
    conn.execute('UPDATE wallet_transactions SET status="failed" WHERE id=?', (wid,))
    desc = f'Hoàn tiền do từ chối yêu cầu rút (mã #{wid})'
    if note:
        desc += f' — Ghi chú: {note}'
    conn.execute(
        'INSERT INTO wallet_transactions (user_id,type,amount,description,status) VALUES (?,?,?,?,?)',
        (uid, 'refund', amount, desc, 'completed')
    )
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Đã từ chối và hoàn {amount:,.0f}₫ vào ví học viên.'})

# ── Admin: Delete Account Requests ────────────────────────────────────
@app.route('/admin/delete-requests')
@admin_required
def admin_delete_requests():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS delete_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT "pending",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    conn.commit()
    page     = int(request.args.get('page', 1))
    per_page = 15
    total    = conn.execute('SELECT COUNT(*) FROM delete_requests').fetchone()[0]
    requests = conn.execute(
        '''SELECT dr.*, u.name as user_name, u.email as user_email
           FROM delete_requests dr JOIN users u ON dr.user_id=u.id
           ORDER BY dr.created_at DESC LIMIT ? OFFSET ?''',
        (per_page, (page-1)*per_page)
    ).fetchall()
    conn.close()
    return render_template('admin/delete_requests.html', requests=requests, total=total,
                           page=page, total_pages=(total+per_page-1)//per_page)

@app.route('/admin/delete-requests/approve/<int:rid>', methods=['POST'])
@admin_required
def admin_approve_delete(rid):
    conn = get_db()
    req = conn.execute('SELECT * FROM delete_requests WHERE id=?', (rid,)).fetchone()
    if not req:
        conn.close(); return jsonify({'success': False, 'message': 'Không tìm thấy yêu cầu.'})
    uid = req['user_id']
    # Xóa các khóa học do người dùng tạo (kèm bài học, tài liệu, bài tập, enrollment)
    created_courses = conn.execute('SELECT id FROM courses WHERE instructor_id=?', (uid,)).fetchall()
    for c in created_courses:
        cid = c['id']
        lesson_ids = [l['id'] for l in conn.execute('SELECT id FROM lessons WHERE course_id=?', (cid,)).fetchall()]
        for lid in lesson_ids:
            conn.execute('DELETE FROM lesson_materials WHERE lesson_id=?', (lid,))
            conn.execute('DELETE FROM lesson_exercises WHERE lesson_id=?', (lid,))
        conn.execute('DELETE FROM lessons WHERE course_id=?', (cid,))
        conn.execute('DELETE FROM enrollments WHERE course_id=?', (cid,))
        conn.execute('DELETE FROM reviews WHERE course_id=?', (cid,))
    conn.execute('DELETE FROM courses WHERE instructor_id=?', (uid,))
    # Xóa dữ liệu học viên
    conn.execute('DELETE FROM enrollments WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM reviews WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM wallet_transactions WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM delete_requests WHERE user_id=?', (uid,))
    conn.execute('DELETE FROM users WHERE id=? AND is_admin=0', (uid,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã xóa tài khoản và toàn bộ khóa học của người dùng!'})

@app.route('/admin/delete-requests/reject/<int:rid>', methods=['POST'])
@admin_required
def admin_reject_delete(rid):
    conn = get_db()
    conn.execute('UPDATE delete_requests SET status="rejected" WHERE id=?', (rid,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã từ chối yêu cầu xóa tài khoản.'})

# ── Admin: Deposit Requests ────────────────────────────────────────────
@app.route('/admin/deposits')
@admin_required
def admin_deposits():
    page     = int(request.args.get('page', 1))
    per_page = 15
    conn     = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS deposit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        transfer_content TEXT DEFAULT "",
        bank_name TEXT DEFAULT "",
        status TEXT DEFAULT "pending",
        note TEXT DEFAULT "",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    conn.commit()
    status_filter = request.args.get('status', '')
    base = '''SELECT dp.*, u.name as user_name, u.email as user_email
              FROM deposit_requests dp JOIN users u ON dp.user_id=u.id WHERE 1=1'''
    params = []
    if status_filter:
        base += ' AND dp.status=?'; params.append(status_filter)
    total    = conn.execute(f'SELECT COUNT(*) FROM ({base})', params).fetchone()[0]
    deposits = conn.execute(base + ' ORDER BY dp.created_at DESC LIMIT ? OFFSET ?',
                            params + [per_page, (page-1)*per_page]).fetchall()
    conn.close()
    return render_template('admin/deposit.html', deposits=deposits, total=total,
                           page=page, total_pages=(total+per_page-1)//per_page,
                           status_filter=status_filter)

@app.route('/admin/deposits/approve/<int:did>', methods=['POST'])
@admin_required
def admin_approve_deposit(did):
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS deposit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        transfer_content TEXT DEFAULT "",
        bank_name TEXT DEFAULT "",
        status TEXT DEFAULT "pending",
        note TEXT DEFAULT "",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    dep = conn.execute('SELECT * FROM deposit_requests WHERE id=?', (did,)).fetchone()
    if not dep:
        conn.close(); return jsonify({'success': False, 'message': 'Không tìm thấy yêu cầu.'})
    if dep['status'] == 'approved':
        conn.close(); return jsonify({'success': False, 'message': 'Yêu cầu này đã được duyệt rồi.'})
    conn.execute('UPDATE users SET wallet_balance=wallet_balance+? WHERE id=?', (dep['amount'], dep['user_id']))
    conn.execute('INSERT INTO wallet_transactions (user_id,type,amount,description,status) VALUES (?,?,?,?,?)',
                 (dep['user_id'], 'deposit', dep['amount'], f'Nạp tiền được duyệt bởi Admin', 'completed'))
    conn.execute('UPDATE deposit_requests SET status="approved" WHERE id=?', (did,))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': f'Đã duyệt và cộng {dep["amount"]:,.0f}₫ vào tài khoản!'})

@app.route('/admin/deposits/reject/<int:did>', methods=['POST'])
@admin_required
def admin_reject_deposit(did):
    note = request.form.get('note', '').strip()
    conn = get_db()
    conn.execute('UPDATE deposit_requests SET status="rejected", note=? WHERE id=?', (note, did))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Đã từ chối yêu cầu nạp tiền.'})

# ── User: Submit Deposit Request ──────────────────────────────────────
@app.route('/wallet/deposit-request', methods=['POST'])
@login_required
def wallet_deposit_request():
    try:
        amount = float(request.form.get('amount', 0))
    except:
        return jsonify({'success': False, 'message': 'Số tiền không hợp lệ.'})
    if amount < 10000:
        return jsonify({'success': False, 'message': 'Số tiền nạp tối thiểu là 10.000₫.'})
    transfer_content = request.form.get('transfer_content', '').strip()
    bank_name        = request.form.get('bank_name', '').strip()
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS deposit_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        transfer_content TEXT DEFAULT "",
        bank_name TEXT DEFAULT "",
        status TEXT DEFAULT "pending",
        note TEXT DEFAULT "",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    conn.execute('INSERT INTO deposit_requests (user_id,amount,transfer_content,bank_name) VALUES (?,?,?,?)',
                 (session['user_id'], amount, transfer_content, bank_name))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'message': 'Yêu cầu nạp tiền đã được gửi! Admin sẽ xác nhận trong vòng 24h.'})

# ── Admin: Add Balance to User ────────────────────────────────────────
@app.route('/admin/users/add-balance/<int:uid>', methods=['POST'])
@admin_required
def admin_add_balance(uid):
    try:
        amount = float(request.form.get('amount', 0))
    except:
        return jsonify({'success': False, 'message': 'Số tiền không hợp lệ.'})
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Số tiền phải lớn hơn 0.'})
    note = request.form.get('note', 'Admin cộng tiền thủ công').strip() or 'Admin cộng tiền thủ công'
    conn = get_db()
    user = conn.execute('SELECT id, name FROM users WHERE id=? AND is_admin=0', (uid,)).fetchone()
    if not user:
        conn.close(); return jsonify({'success': False, 'message': 'Không tìm thấy người dùng.'})
    conn.execute('UPDATE users SET wallet_balance=wallet_balance+? WHERE id=?', (amount, uid))
    conn.execute('INSERT INTO wallet_transactions (user_id,type,amount,description,status) VALUES (?,?,?,?,?)',
                 (uid, 'deposit', amount, note, 'completed'))
    conn.commit()
    new_balance = conn.execute('SELECT wallet_balance FROM users WHERE id=?', (uid,)).fetchone()['wallet_balance']
    conn.close()
    return jsonify({'success': True,
                    'message': f'Đã cộng {amount:,.0f}₫ vào tài khoản {user["name"]}!',
                    'new_balance': new_balance})

if __name__ == '__main__':
    # Tự tạo DB lần đầu nếu chưa có file sqlite.
    if not os.path.exists(DB):
        init_db()
    # Bind 0.0.0.0 để thiết bị di động trong cùng mạng LAN gọi được API.
    app.run(host='0.0.0.0', debug=True, port=5000)
"""本地人脸考勤服务。正常模式使用 MySQL，--demo 使用独立演示数据库。"""
import argparse
import csv
import io
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, session
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from db import Attendance, AuditEvent, Base, FaceTemplate, Setting, User
from faces import FaceEngine, FaceError

ROOT = Path(__file__).resolve().parent
BJ = timezone(timedelta(hours=8))
DEFAULTS = {"shift_start": "09:00", "shift_end": "18:00", "grace_minutes": "5", "face_threshold": "0.50", "organization": "云帆科技"}

class APIError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status

def local_now():
    return datetime.now(BJ).replace(tzinfo=None)

def persistent_key(name, generator):
    folder = ROOT / "data"
    folder.mkdir(exist_ok=True)
    file = folder / name
    if not file.exists():
        # 排他创建防止并发生成不同密钥。
        try:
            with file.open("x", encoding="utf-8") as stream:
                stream.write(generator())
        except FileExistsError:
            pass
    return file.read_text(encoding="utf-8").strip()

def mysql_url(database=True):
    return URL.create("mysql+pymysql", username=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASSWORD", ""), host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("MYSQL_PORT", "3306")), database=os.getenv("MYSQL_DATABASE", "face_attendance") if database else None, query={"charset": "utf8mb4"})

def create_app(overrides=None, demo=False):
    load_dotenv(ROOT / ".env", encoding="utf-8-sig", override=True)
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(SECRET_KEY=os.getenv("SECRET_KEY") or persistent_key("session.key", lambda: secrets.token_hex(32)), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true", PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=9_000_000, DEMO=demo, NOW=local_now)
    if overrides:
        app.config.update(overrides)
    url = app.config.get("DATABASE_URL") or (f"sqlite:///{(ROOT / 'data' / 'demo.sqlite3').as_posix()}" if demo else mysql_url())
    options = {"pool_pre_ping": True}
    if str(url).startswith("mysql"):
        options["connect_args"] = {"connect_timeout": 3, "read_timeout": 5, "write_timeout": 5}
    engine = create_engine(url, **options)
    factory = sessionmaker(engine, expire_on_commit=False)
    key = app.config.get("FACE_KEY") or os.getenv("FACE_ENCRYPTION_KEY") or persistent_key("face.key", lambda: Fernet.generate_key().decode())
    face = app.config.get("FACE_ENGINE") or FaceEngine(ROOT / "models", key)
    app.extensions.update(db_engine=engine, db_factory=factory, face_engine=face)
    rates, rate_lock = defaultdict(deque), threading.Lock()
    if demo or app.config.get("TESTING"):
        Base.metadata.create_all(engine)
    if demo:
        seed_demo(factory)

    def now():
        return app.config["NOW"]()

    def throttle(key, limit=10, window=60):
        with rate_lock:
            stamp = time.monotonic()
            queue = rates[key]
            while queue and queue[0] < stamp - window:
                queue.popleft()
            if len(queue) >= limit:
                raise APIError("操作过于频繁，请稍后重试", 429)
            queue.append(stamp)
            # 回收陈旧限流键，避免不断增长。
            if len(rates) > 1000:
                for old_key in list(rates):
                    if not rates[old_key] or rates[old_key][-1] < stamp - window:
                        del rates[old_key]

    def db_route(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with factory.begin() as db:
                g.db = db
                return fn(*args, **kwargs)
        return wrapped

    def access(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                user = g.db.get(User, session.get("uid", -1))
                if not user or not user.active or session.get("version") != user.session_version:
                    session.pop("uid", None)
                    raise APIError("请先登录", 401)
                if admin and user.role != "admin":
                    raise APIError("此操作需要管理员权限", 403)
                g.user = user
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    def settings():
        result = DEFAULTS.copy()
        for setting in g.db.scalars(select(Setting)):
            result[setting.key] = setting.value
        return result

    def audit(action, target):
        g.db.add(AuditEvent(actor_id=g.user.id, action=action, target=str(target), created_at=now()))

    def user_json(user):
        template = g.db.get(FaceTemplate, user.id)
        return {"id": user.id, "username": user.username, "employee_no": user.employee_no, "name": user.name, "department": user.department, "role": user.role, "active": user.active, "face_enrolled": template is not None, "enrolled_at": template.enrolled_at.isoformat() if template else None}

    def attendance_json(row, user):
        minutes = int((row.check_out - row.check_in).total_seconds() / 60) if row.check_out and row.check_in else None
        return {"id": row.id, "user_id": user.id, "name": user.name, "employee_no": user.employee_no, "department": user.department, "date": row.work_date.isoformat(), "check_in": row.check_in.strftime("%H:%M:%S") if row.check_in else None, "check_out": row.check_out.strftime("%H:%M:%S") if row.check_out else None, "in_status": row.in_status, "out_status": row.out_status, "worked_minutes": minutes, "shift_start": row.shift_start, "shift_end": row.shift_end, "grace_minutes": row.grace_minutes}

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise APIError("请求格式无效")
        return data

    def field(data, key, maximum=80):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise APIError(f"字段 {key} 不能为空且不能超过 {maximum} 字符")
        return value.strip()

    def password(data):
        value = data.get("password")
        if not isinstance(value, str) or not 10 <= len(value) <= 128:
            raise APIError("密码长度须为 10 至 128 个字符")
        return value

    def time_field(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise APIError("班次时间格式须为 HH:MM")
        return value

    @app.before_request
    def protect():
        if not request.path.startswith("/api/"):
            return
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            received = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(received, session["csrf"]):
                raise APIError("请求校验失败，请刷新页面重试", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(FaceError)
    def face_error(error):
        return jsonify(error=str(error)), 422

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        return jsonify(error="该账号、工号或当日打卡记录已存在，请刷新后重试"), 409

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        # 不把连接字符串、密码或底层 SQL 返回给浏览器。
        return jsonify(error="数据库尚未连接或初始化，请检查 .env 并执行 init-db"), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error="请求过大" if error.code == 413 else "请求地址或格式无效"), error.code

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/status")
    def status():
        try:
            ready = inspect(engine).has_table("users")
            with factory() as db:
                needs_setup = ready and db.scalar(select(func.count()).select_from(User)) == 0
        except SQLAlchemyError:
            ready, needs_setup = False, False
        return jsonify(db_ready=ready, needs_setup=needs_setup, models_ready=face.ready, demo=demo, csrf=session["csrf"], server_time=now().isoformat(), timezone="Asia/Shanghai")

    @app.post("/api/setup")
    @db_route
    def setup():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            raise APIError("首次设置仅允许在本机进行", 403)
        if g.db.scalar(select(func.count()).select_from(User)):
            raise APIError("系统已初始化，请登录", 409)
        data = payload()
        account = field(data, "username", 60)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,60}", account):
            raise APIError("账号应为 3 至 60 个英文字母、数字或 ._- ")
        user = User(username=account, employee_no="ADMIN001", name=field(data, "name", 60), department="管理部", role="admin", password_hash=generate_password_hash(password(data)))
        g.db.add(user)
        g.db.flush()
        return jsonify(message="管理员已创建，请登录"), 201

    @app.post("/api/login")
    @db_route
    def login():
        throttle(("login", request.remote_addr))
        data = payload()
        account = field(data, "username", 60)
        secret = data.get("password", "")
        if not isinstance(secret, str) or len(secret) > 128:
            raise APIError("账号或密码错误", 401)
        user = g.db.scalar(select(User).where(User.username == account))
        if not user or not user.active or not check_password_hash(user.password_hash, secret):
            raise APIError("账号或密码错误，或账号已停用", 401)
        session.clear()
        session.update(uid=user.id, version=user.session_version, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return jsonify(user=user_json(user), csrf=session["csrf"])

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(message="已退出登录")

    @app.get("/api/me")
    @db_route
    @access()
    def me():
        return jsonify(user=user_json(g.user), settings=settings(), csrf=session["csrf"])

    @app.get("/api/dashboard")
    @db_route
    @access()
    def dashboard():
        today = now().date()
        query = select(Attendance, User).join(User).where(Attendance.work_date == today)
        if g.user.role != "admin":
            query = query.where(User.id == g.user.id)
        pairs = g.db.execute(query).all()
        scope = select(User).where(User.active.is_(True))
        if g.user.role != "admin":
            scope = scope.where(User.id == g.user.id)
        people = g.db.scalars(scope).all()
        stats = {"total": len(people), "checked_in": sum(bool(r.check_in) for r, u in pairs if u.active), "checked_out": sum(bool(r.check_out) for r, u in pairs if u.active), "late": sum(r.in_status == "late" for r, u in pairs if u.active)}
        my_row = g.db.scalar(select(Attendance).where(Attendance.user_id == g.user.id, Attendance.work_date == today))
        return jsonify(stats=stats, today=attendance_json(my_row, g.user) if my_row else None, records=[attendance_json(r, u) for r, u in pairs], server_time=now().isoformat(), settings=settings(), face_enrolled=g.db.get(FaceTemplate, g.user.id) is not None, models_ready=face.ready)

    @app.post("/api/attendance/punch")
    @db_route
    @access()
    def punch():
        throttle(("face", g.user.id), limit=8)
        data = payload()
        kind = data.get("kind")
        if kind not in {"in", "out"}:
            raise APIError("请选择上班或下班打卡")
        # 目标始终来自后端会话，忽略客户端提供的用户 ID。
        template = g.db.get(FaceTemplate, g.user.id)
        if not template:
            raise APIError("尚未录入人脸，请联系管理员", 409)
        stamp = now()
        row = g.db.scalar(select(Attendance).where(Attendance.user_id == g.user.id, Attendance.work_date == stamp.date()).with_for_update())
        if kind == "in" and row and row.check_in:
            raise APIError("今天已完成上班打卡", 409)
        if kind == "out" and (not row or not row.check_in):
            raise APIError("请先完成今天的上班打卡", 409)
        if kind == "out" and row.check_out:
            raise APIError("今天已完成下班打卡", 409)
        config = settings()
        feature = face.extract(data.get("image"))
        score = face.score(feature, face.decrypt(template.encrypted_features))
        if score < float(config["face_threshold"]):
            raise APIError("人脸与当前登录员工不匹配，请本人打卡", 422)
        # 核验后再取时间，避免将模型处理时间计入请求开始时间。
        stamp = now()
        if row and row.work_date != stamp.date():
            raise APIError("日期已变化，请刷新后重新打卡", 409)
        if not row:
            row = Attendance(user_id=g.user.id, work_date=stamp.date(), shift_start=config["shift_start"], shift_end=config["shift_end"], grace_minutes=int(config["grace_minutes"]))
            g.db.add(row)
        start = datetime.combine(stamp.date(), datetime.strptime(row.shift_start, "%H:%M").time()) + timedelta(minutes=row.grace_minutes)
        end = datetime.combine(stamp.date(), datetime.strptime(row.shift_end, "%H:%M").time())
        if kind == "in":
            row.check_in, row.in_score, row.in_status = stamp, score, "late" if stamp > start else "normal"
        else:
            if stamp <= row.check_in:
                raise APIError("下班时间必须晚于上班时间", 409)
            row.check_out, row.out_score, row.out_status = stamp, score, "early" if stamp < end else "normal"
        g.db.flush()
        audit("check_in" if kind == "in" else "check_out", row.id)
        return jsonify(message="上班打卡成功" if kind == "in" else "下班打卡成功", record=attendance_json(row, g.user), similarity=round(score, 4))

    def records_query():
        try:
            start = date.fromisoformat(request.args.get("start", now().date().replace(day=1).isoformat()))
            end = date.fromisoformat(request.args.get("end", now().date().isoformat()))
        except ValueError:
            raise APIError("日期格式无效") from None
        if end < start or (end - start).days > 366:
            raise APIError("请查询一年以内的有效日期范围")
        query = select(Attendance, User).join(User).where(Attendance.work_date.between(start, end))
        if g.user.role != "admin":
            query = query.where(User.id == g.user.id)
        elif request.args.get("user_id"):
            try:
                query = query.where(User.id == int(request.args["user_id"]))
            except ValueError:
                raise APIError("员工参数无效") from None
        search = request.args.get("search", "").strip()[:80]
        if search:
            # SQL 参数化；转义 LIKE 通配符。
            pattern = "%" + search.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            query = query.where(User.name.like(pattern, escape="!") | User.employee_no.like(pattern, escape="!"))
        return query.order_by(Attendance.work_date.desc(), User.employee_no)

    @app.get("/api/attendance")
    @db_route
    @access()
    def records():
        query = records_query()
        try:
            page = max(1, min(10000, int(request.args.get("page", 1))))
        except ValueError:
            raise APIError("页码无效") from None
        count = g.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = g.db.execute(query.offset((page - 1) * 25).limit(25)).all()
        return jsonify(records=[attendance_json(r, u) for r, u in rows], total=count, page=page, page_size=25)

    @app.get("/api/attendance/export")
    @db_route
    @access()
    def export():
        rows = g.db.execute(records_query().limit(20000)).all()
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["日期", "工号", "姓名", "部门", "上班", "下班", "上班状态", "下班状态", "在岗分钟"])
        labels = {"normal": "正常", "late": "迟到", "early": "早退", None: "未打卡"}
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
        for row, user in rows:
            data = attendance_json(row, user)
            writer.writerow([data["date"], safe(user.employee_no), safe(user.name), safe(user.department), data["check_in"] or "", data["check_out"] or "", labels[row.in_status], labels[row.out_status], data["worked_minutes"] if data["worked_minutes"] is not None else ""])
        return Response("\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="attendance.csv"'})

    @app.get("/api/users")
    @db_route
    @access(admin=True)
    def users():
        return jsonify(users=[user_json(u) for u in g.db.scalars(select(User).order_by(User.id))])

    @app.post("/api/users")
    @db_route
    @access(admin=True)
    def add_user():
        data = payload()
        account = field(data, "username", 60)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,60}", account):
            raise APIError("账号应为 3 至 60 个英文字母、数字或 ._-")
        role = data.get("role", "employee")
        if role not in {"admin", "employee"}:
            raise APIError("角色无效")
        user = User(username=account, employee_no=field(data, "employee_no", 40), name=field(data, "name", 60), department=field(data, "department", 80), role=role, password_hash=generate_password_hash(password(data)))
        g.db.add(user)
        g.db.flush()
        audit("create_user", user.id)
        return jsonify(user=user_json(user)), 201

    @app.patch("/api/users/<int:user_id>")
    @db_route
    @access(admin=True)
    def update_user(user_id):
        target = g.db.get(User, user_id)
        if not target:
            raise APIError("员工不存在", 404)
        data = payload()
        if "active" in data and not isinstance(data["active"], bool):
            raise APIError("账号状态无效")
        role = data.get("role", target.role)
        active = data.get("active", target.active)
        if role not in {"admin", "employee"}:
            raise APIError("角色无效")
        if user_id == g.user.id and (role != "admin" or not active):
            raise APIError("不能停用自己或移除自己的管理员权限", 409)
        for key, limit in [("name", 60), ("department", 80), ("employee_no", 40)]:
            if key in data:
                setattr(target, key, field(data, key, limit))
        if target.role != role or target.active != active or data.get("password"):
            target.session_version += 1
        target.role, target.active = role, active
        if data.get("password"):
            target.password_hash = generate_password_hash(password(data))
        audit("update_user", target.id)
        g.db.flush()
        return jsonify(user=user_json(target))

    @app.post("/api/users/<int:user_id>/face")
    @db_route
    @access(admin=True)
    def enroll(user_id):
        throttle(("enroll", g.user.id), limit=5)
        user = g.db.get(User, user_id)
        if not user or not user.active:
            raise APIError("员工不存在或已停用", 404)
        data = payload()
        if data.get("consent") is not True:
            raise APIError("请取得员工同意后录入")
        images = data.get("images")
        if not isinstance(images, list) or not 3 <= len(images) <= 5:
            raise APIError("请采集 3 至 5 张清晰人脸照片")
        features = [face.extract(image) for image in images]
        threshold = float(settings()["face_threshold"])
        if any(face.score(v, [features[0]]) < threshold for v in features[1:]):
            raise APIError("采集照片身份不一致，请重新录入", 422)
        for template in g.db.scalars(select(FaceTemplate).where(FaceTemplate.user_id != user_id)):
            if face.score(features[0], face.decrypt(template.encrypted_features)) >= threshold:
                raise APIError("该人脸已关联其他员工，请核对身份", 409)
        template = g.db.get(FaceTemplate, user_id) or FaceTemplate(user_id=user_id)
        template.encrypted_features = face.encrypt(features)
        template.sample_count, template.enrolled_at = len(features), now()
        g.db.add(template)
        audit("enroll_face", user_id)
        return jsonify(message=f"{user.name}的人脸已录入", samples=len(features))

    @app.get("/api/settings")
    @db_route
    @access(admin=True)
    def get_settings():
        return jsonify(settings=settings())

    @app.put("/api/settings")
    @db_route
    @access(admin=True)
    def put_settings():
        data = payload()
        start, end = time_field(data.get("shift_start")), time_field(data.get("shift_end"))
        if end <= start:
            raise APIError("当前版本支持同日班次，下班时间须晚于上班时间")
        try:
            grace = int(data.get("grace_minutes", 0))
            threshold = float(data.get("face_threshold", 0.5))
        except (ValueError, TypeError, OverflowError):
            raise APIError("宽限时间或识别阈值无效") from None
        if not 0 <= grace <= 60 or not 0.363 <= threshold <= 0.95:
            raise APIError("宽限须为 0 至 60 分钟，阈值须为 0.363 至 0.95")
        values = dict(shift_start=start, shift_end=end, grace_minutes=str(grace), face_threshold=str(threshold), organization=field(data, "organization", 80))
        for key, value in values.items():
            setting = g.db.get(Setting, key) or Setting(key=key)
            setting.value = value
            g.db.add(setting)
        audit("update_settings", "shift")
        return jsonify(settings=values, message="设置已保存，已开始的班次保留原规则")

    return app

def seed_demo(factory):
    with factory.begin() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return
        people = [("admin", "林知夏", "管理部", "admin"), ("employee", "陈一然", "产品设计部", "employee"), ("zhou", "周明远", "研发部", "employee"), ("xu", "许清禾", "产品设计部", "employee"), ("song", "宋以安", "运营部", "employee"), ("lu", "陆星辰", "研发部", "employee")]
        today = local_now().date()
        for index, (account, name, department, role) in enumerate(people):
            user = User(username=account, employee_no=f"YF{1001 + index}", name=name, department=department, role=role, password_hash=generate_password_hash("DemoAttend2026!"))
            db.add(user)
            db.flush()
            for days in range(1, 6):
                day = today - timedelta(days=days)
                if day.weekday() > 4:
                    continue
                db.add(Attendance(user_id=user.id, work_date=day, check_in=datetime.combine(day, datetime.strptime("08:5" + str(index), "%H:%M").time()), check_out=datetime.combine(day, datetime.strptime("18:1" + str(index), "%H:%M").time()), in_status="normal", out_status="normal", shift_start="09:00", shift_end="18:00", grace_minutes=5))
            if index in {1, 2, 3, 4}:
                db.add(Attendance(user_id=user.id, work_date=today, check_in=datetime.combine(today, datetime.strptime("09:12" if index == 2 else "08:5" + str(index), "%H:%M").time()), in_status="late" if index == 2 else "normal", shift_start="09:00", shift_end="18:00", grace_minutes=5))

def init_database():
    load_dotenv(ROOT / ".env", encoding="utf-8-sig", override=True)
    database = os.getenv("MYSQL_DATABASE", "face_attendance")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
        raise SystemExit("库名仅允许字母、数字、下划线")
    server = create_engine(mysql_url(False), connect_args={"connect_timeout": 5})
    with server.begin() as connection:
        connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    engine = create_engine(mysql_url())
    Base.metadata.create_all(engine)
    print("MySQL 数据库和表已初始化。打开网页设置首个管理员。")
    engine.dispose()
    server.dispose()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["serve", "init-db"], default="serve")
    parser.add_argument("--demo", action="store_true", help="使用独立 SQLite 演示库，不读取 MySQL 人员数据")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    if args.command == "init-db":
        try:
            init_database()
        except SQLAlchemyError:
            raise SystemExit("MySQL 初始化失败。请检查服务状态、.env 密码及建库权限；密码未输出。") from None
    else:
        from waitress import serve
        application = create_app(demo=args.demo)
        port = args.port or int(os.getenv("PORT", "5080"))
        host = os.getenv("HOST", "127.0.0.1")
        print(f"人脸考勤系统：http://{host}:{port} {'（演示模式）' if args.demo else '（MySQL 模式）'}", flush=True)
        serve(application, host=host, port=port, threads=4)

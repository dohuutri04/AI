import json
import os
from datetime import datetime
from urllib import error as urlerror
from urllib import request as urlrequest

# =============================================================================
# AI PERSONALIZATION SERVICE
# -----------------------------------------------------------------------------
# Module này chỉ chứa logic AI nghiệp vụ (không chứa Flask route):
# 1) Phân tích dữ liệu học tập từ DB
# 2) Tính risk score/segment
# 3) Sinh gợi ý bài học/khóa học/kế hoạch
# 4) Sinh coach message theo hybrid mode:
#    - Gemini cloud nếu khả dụng
#    - Fallback rule_engine nội bộ khi cloud lỗi/không cấu hình
# =============================================================================


def parse_db_datetime(value):
    """Parse datetime text from SQLite safely."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def generate_internal_coach_message(ai_profile):
    """Free/offline coach message based on user behavior metrics."""
    risk = ai_profile.get("risk_level", "low")
    segment = ai_profile.get("segment", "steady")
    inactivity_days = ai_profile.get("inactivity_days", 0)
    avg_progress = ai_profile.get("avg_progress", 0)
    next_lessons = ai_profile.get("next_lessons", [])
    next_steps = ai_profile.get("next_steps", [])

    focus_line = "Mục tiêu tuần này: duy trì đều 30-45 phút mỗi ngày."
    if risk == "high":
        focus_line = "Mục tiêu tuần này: khôi phục nhịp học bằng 1 bài/ngày trong 7 ngày."
    elif risk == "medium":
        focus_line = "Mục tiêu tuần này: hoàn thành ít nhất 3 bài để kéo tiến độ lên ổn định."
    elif segment == "fast_track":
        focus_line = "Mục tiêu tuần này: tăng tốc hoàn thành 1 mốc lớn và bắt đầu 1 chủ đề nâng cao."

    first_action = "Bước đầu tiên hôm nay: mở lại khóa đang học và hoàn thành 1 bài ngắn."
    if next_lessons:
        lesson = next_lessons[0]
        first_action = (
            f"Bước đầu tiên hôm nay: học ngay bài '{lesson.get('lesson_title', 'bài kế tiếp')}' "
            f"trong khóa '{lesson.get('course_title', 'khóa hiện tại')}'."
        )

    nudge = "Bạn đang đi đúng hướng, chỉ cần giữ nhịp đều là sẽ thấy tiến bộ rõ rệt."
    if inactivity_days >= 5:
        nudge = "Bạn đã gián đoạn vài ngày, hãy bắt đầu lại bằng mục tiêu thật nhỏ để lấy đà."

    details = next_steps[0] if next_steps else "Ưu tiên hoàn thành khóa có tiến độ cao nhất trước."
    message = (
        f"AI nội bộ phân tích thấy tiến độ trung bình của bạn đang ở {avg_progress}%.\n"
        f"{focus_line}\n"
        f"{first_action}\n"
        f"Gợi ý trọng tâm: {details}\n"
        f"{nudge}"
    )
    return {"text": message, "source": "rule_engine", "enabled": True}


def generate_gemini_coach_message(ai_profile, logger):
    """Try cloud AI (Gemini). Return None when unavailable/fails."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    if not api_key:
        return None

    prompt = (
        "Bạn là AI coach học tập cho nền tảng EduConnect. "
        "Hãy viết phản hồi tiếng Việt, ngắn gọn (4-6 dòng), giọng động viên, cụ thể hành động. "
        "Không dùng markdown. Dữ liệu học viên: "
        f"segment={ai_profile.get('segment')}, "
        f"avg_progress={ai_profile.get('avg_progress')}%, "
        f"risk_level={ai_profile.get('risk_level')}, "
        f"risk_score={ai_profile.get('risk_score')}, "
        f"inactivity_days={ai_profile.get('inactivity_days')}, "
        f"completed={ai_profile.get('completed_count')}, "
        f"in_progress={ai_profile.get('in_progress_count')}, "
        f"stalled={ai_profile.get('stalled_count')}. "
        "Trả về kế hoạch tuần này gồm: mục tiêu chính, thời lượng mỗi ngày, và bước đầu tiên hôm nay."
    )

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 220},
    }

    req = urlrequest.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        candidates = body.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts and parts[0].get("text"):
                return {"text": parts[0]["text"].strip(), "source": "gemini", "enabled": True}
    except urlerror.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            err_body = ""
        logger.warning("Gemini HTTPError %s: %s", getattr(e, "code", "unknown"), err_body[:500])
        return None
    except (urlerror.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning("Gemini request error: %s", str(e))
        return None
    return None


def generate_ai_personalization(user_id, get_db, logger):
    """
    Build AI personalization profile from user behavior.

    This service is intentionally isolated from Flask routes so it is
    easier to read, test, and extend independently.
    """
    # B1: đọc dữ liệu nền từ DB (enrollments, lesson_progress, courses...)
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lesson_progress (
        user_id INTEGER, lesson_id INTEGER,
        completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, lesson_id))"""
    )
    enrolled = conn.execute(
        "SELECT e.course_id, e.progress, c.title, c.category_id, c.level, c.price, c.total_lessons "
        "FROM enrollments e JOIN courses c ON e.course_id=c.id "
        "WHERE e.user_id=?",
        (user_id,),
    ).fetchall()

    completed_count = 0
    in_progress_count = 0
    stalled_count = 0
    avg_progress = 0
    category_scores = {}
    level_scores = {}

    if enrolled:
        total_progress = 0
        for row in enrolled:
            progress = int(row["progress"] or 0)
            total_progress += progress
            if progress >= 100:
                completed_count += 1
            elif progress > 0:
                in_progress_count += 1
            else:
                stalled_count += 1

            cat = row["category_id"]
            lvl = row["level"] or "beginner"
            if cat:
                category_scores[cat] = category_scores.get(cat, 0) + max(progress, 20)
            level_scores[lvl] = level_scores.get(lvl, 0) + max(progress, 20)

        avg_progress = round(total_progress / len(enrolled))

    # B2: phân loại nhóm học viên dựa vào tiến độ tổng quan.
    if not enrolled:
        learner_segment = "new"
    elif avg_progress >= 70 and completed_count >= 2:
        learner_segment = "fast_track"
    elif stalled_count >= max(1, len(enrolled) // 2):
        learner_segment = "at_risk"
    else:
        learner_segment = "steady"

    focus_category_ids = [k for k, _ in sorted(category_scores.items(), key=lambda x: x[1], reverse=True)[:2]]
    focus_levels = [k for k, _ in sorted(level_scores.items(), key=lambda x: x[1], reverse=True)[:2]]

    category_filter = ""
    params = []
    if focus_category_ids:
        placeholders = ",".join(["?"] * len(focus_category_ids))
        category_filter = f" AND c.category_id IN ({placeholders}) "
        params.extend(focus_category_ids)

    # B3: gợi ý khóa học mới dựa trên category/level người dùng đang tập trung.
    recommendations = conn.execute(
        "SELECT c.id, c.title, c.price, c.level, c.total_students, c.rating, "
        "cat.name as category_name, u.name as instructor_name "
        "FROM courses c "
        "LEFT JOIN categories cat ON c.category_id=cat.id "
        "LEFT JOIN users u ON c.instructor_id=u.id "
        "WHERE c.id NOT IN (SELECT course_id FROM enrollments WHERE user_id=?) "
        + category_filter
        + "ORDER BY c.rating DESC, c.total_students DESC LIMIT 6",
        [user_id] + params,
    ).fetchall()

    if not recommendations:
        recommendations = conn.execute(
            "SELECT c.id, c.title, c.price, c.level, c.total_students, c.rating, "
            "cat.name as category_name, u.name as instructor_name "
            "FROM courses c "
            "LEFT JOIN categories cat ON c.category_id=cat.id "
            "LEFT JOIN users u ON c.instructor_id=u.id "
            "WHERE c.id NOT IN (SELECT course_id FROM enrollments WHERE user_id=?) "
            "ORDER BY c.rating DESC, c.total_students DESC LIMIT 6",
            (user_id,),
        ).fetchall()

    latest_completed = conn.execute(
        "SELECT MAX(completed_at) AS latest_completed FROM lesson_progress WHERE user_id=?",
        (user_id,),
    ).fetchone()
    latest_enroll = conn.execute(
        "SELECT MAX(enrolled_at) AS latest_enrolled FROM enrollments WHERE user_id=?",
        (user_id,),
    ).fetchone()
    last_completed_dt = parse_db_datetime(latest_completed["latest_completed"]) if latest_completed else None
    last_enrolled_dt = parse_db_datetime(latest_enroll["latest_enrolled"]) if latest_enroll else None
    candidate_dates = [d for d in [last_completed_dt, last_enrolled_dt] if d]
    inactivity_days = (datetime.now() - max(candidate_dates)).days if candidate_dates else 0

    # B4: tính điểm rủi ro bỏ học (risk_score 0-100).
    total_enrolled = len(enrolled)
    stalled_ratio = (stalled_count / total_enrolled) if total_enrolled else 0
    risk_score = 0
    if total_enrolled:
        risk_score += max(0, 60 - avg_progress) * 0.6
        risk_score += stalled_ratio * 35
        if inactivity_days > 3:
            risk_score += min(35, (inactivity_days - 3) * 2.2)
        if completed_count >= 2 and avg_progress >= 70:
            risk_score -= 15
    risk_score = max(0, min(100, round(risk_score)))

    if risk_score >= 70:
        risk_level = "high"
    elif risk_score >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"

    # B5: xác định bài học kế tiếp cho các khóa đang học.
    next_lessons = conn.execute(
        "SELECT c.id AS course_id, c.title AS course_title, e.progress, "
        "(SELECT l.id FROM lessons l "
        " WHERE l.course_id=c.id AND l.id NOT IN (SELECT lp.lesson_id FROM lesson_progress lp WHERE lp.user_id=?) "
        " ORDER BY l.order_num, l.id LIMIT 1) AS next_lesson_id, "
        "(SELECT l.title FROM lessons l "
        " WHERE l.course_id=c.id AND l.id NOT IN (SELECT lp.lesson_id FROM lesson_progress lp WHERE lp.user_id=?) "
        " ORDER BY l.order_num, l.id LIMIT 1) AS next_lesson_title "
        "FROM enrollments e JOIN courses c ON e.course_id=c.id "
        "WHERE e.user_id=? "
        "ORDER BY CASE WHEN e.progress BETWEEN 1 AND 99 THEN 0 ELSE 1 END, e.progress ASC "
        "LIMIT 5",
        (user_id, user_id, user_id),
    ).fetchall()

    next_lesson_suggestions = []
    for item in next_lessons:
        if item["next_lesson_id"] and int(item["progress"] or 0) < 100:
            next_lesson_suggestions.append(
                {
                    "course_id": item["course_id"],
                    "course_title": item["course_title"],
                    "progress": int(item["progress"] or 0),
                    "lesson_id": item["next_lesson_id"],
                    "lesson_title": item["next_lesson_title"],
                }
            )

    if learner_segment == "new":
        next_steps = [
            "Bắt đầu với 1 khóa cơ bản phù hợp mục tiêu nghề nghiệp của bạn.",
            "Dành 30-45 phút mỗi ngày để tạo nhịp học ổn định.",
            "Hoàn thành ít nhất 2 bài đầu trong 48 giờ đầu tiên.",
        ]
    elif learner_segment == "at_risk":
        next_steps = [
            "Tạm dừng đăng ký thêm khóa mới, ưu tiên hoàn thành khóa đang học.",
            "Đặt mục tiêu nhỏ: 1 bài học mỗi ngày trong 7 ngày tới.",
            "Ôn lại các bài miễn phí trước khi quay lại bài nâng cao.",
        ]
    elif learner_segment == "fast_track":
        next_steps = [
            "Tăng tốc với khóa nâng cao để mở rộng kỹ năng chuyên sâu.",
            "Kết hợp 1 khóa kỹ thuật + 1 khóa kinh doanh để tối ưu thu nhập.",
            "Đặt mục tiêu hoàn thành thêm 1 khóa trong 2-3 tuần tới.",
        ]
    else:
        next_steps = [
            "Giữ nhịp học hiện tại và nâng dần lên 45-60 phút/ngày.",
            "Ưu tiên khóa có tiến độ cao nhất để sớm đạt 100%.",
            "Sau khi hoàn thành 1 khóa, chọn khóa cùng chủ đề để đào sâu.",
        ]

    ai_profile = {
        "segment": learner_segment,
        "avg_progress": avg_progress,
        "completed_count": completed_count,
        "in_progress_count": in_progress_count,
        "stalled_count": stalled_count,
        "focus_levels": focus_levels,
        "recommendations": [dict(r) for r in recommendations],
        "next_steps": next_steps,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "inactivity_days": inactivity_days,
        "next_lessons": next_lesson_suggestions,
    }

    # AI reminder để nhắc học chủ động ngoài dashboard tĩnh.
    # Mức nhắc dựa trên inactivity_days và risk_level.
    if inactivity_days >= 7 or risk_level == "high":
        ai_profile["reminder"] = {
            "level": "high",
            "title": "⚠️ Nhắc học khẩn",
            "message": "Bạn đã gián đoạn nhiều ngày. Hãy học lại 1 bài trong hôm nay để tránh rơi vào trạng thái bỏ dở."
        }
    elif inactivity_days >= 3 or risk_level == "medium":
        ai_profile["reminder"] = {
            "level": "medium",
            "title": "🔔 Nhắc học",
            "message": "Bạn đang chậm nhịp học. Hãy dành 20-30 phút tối nay để hoàn thành 1 bài ngắn."
        }
    else:
        ai_profile["reminder"] = {
            "level": "low",
            "title": "✅ Duy trì nhịp học tốt",
            "message": "Bạn đang giữ nhịp ổn. Tiếp tục duy trì lịch học đều để hoàn thành khóa nhanh hơn."
        }

    # Tóm tắt tiến độ kế hoạch 3 ngày gần nhất để hiển thị nhanh trên tab AI.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lesson_study_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        score_pct INTEGER NOT NULL,
        plan_json TEXT NOT NULL,
        progress_json TEXT DEFAULT "[]",
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )"""
    )
    try:
        conn.execute('ALTER TABLE lesson_study_plans ADD COLUMN progress_json TEXT DEFAULT "[]"')
    except Exception:
        pass
    latest_plan = conn.execute(
        "SELECT id, lesson_id, score_pct, plan_json, progress_json, created_at "
        "FROM lesson_study_plans WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if latest_plan:
        try:
            plan_items = json.loads(latest_plan["plan_json"] or "[]")
            if not isinstance(plan_items, list):
                plan_items = []
        except Exception:
            plan_items = []
        try:
            progress_items = json.loads(latest_plan["progress_json"] or "[]")
            if not isinstance(progress_items, list):
                progress_items = []
        except Exception:
            progress_items = []
        total_days = max(1, min(3, len(plan_items)))
        if len(progress_items) < total_days:
            progress_items = progress_items + [False] * (total_days - len(progress_items))
        progress_items = [bool(x) for x in progress_items[:total_days]]
        completed_days = sum(1 for x in progress_items if x)
        ai_profile["latest_study_plan"] = {
            "plan_id": int(latest_plan["id"]),
            "lesson_id": int(latest_plan["lesson_id"] or 0),
            "score_pct": int(latest_plan["score_pct"] or 0),
            "total_days": total_days,
            "completed_days": completed_days,
            "progress_pct": round((completed_days / total_days) * 100),
            "created_at": latest_plan["created_at"],
        }
    else:
        ai_profile["latest_study_plan"] = {
            "plan_id": None,
            "lesson_id": None,
            "score_pct": 0,
            "total_days": 0,
            "completed_days": 0,
            "progress_pct": 0,
            "created_at": None,
        }

    # B6: sinh thông điệp AI coach theo mode cấu hình.
    # AI_COACH_MODE:
    # - auto (default): ưu tiên AI cloud (nếu sẵn có), lỗi thì fallback nội bộ
    # - internal: luôn dùng AI nội bộ miễn phí
    ai_mode = os.environ.get("AI_COACH_MODE", "auto").strip().lower()
    coach = None
    if ai_mode != "internal":
        coach = generate_gemini_coach_message(ai_profile, logger)
    if not coach:
        coach = generate_internal_coach_message(ai_profile)

    ai_profile["coach_message"] = coach["text"]
    ai_profile["coach_source"] = coach["source"]
    ai_profile["gemini_enabled"] = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    conn.close()
    return ai_profile

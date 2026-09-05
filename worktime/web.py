from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .core import (
    DAY_NAMES,
    DAY_TYPE_LABELS,
    MONTH_NAMES,
    calendar_schedule_details,
    clock_now_text,
    entry_metrics,
    format_clock,
    format_duration,
    iter_month_days,
    month_shift,
    parse_hms,
    schedule_details,
    utc_now,
)
from .db import add_default_schedule, get_db, init_app
from .exporter import build_export
from .importer import WorkbookImportError, import_export_workbook


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    project_root = Path(__file__).resolve().parent.parent
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("APP_SECRET", "csereld-le-egy-hosszu-veletlen-szovegre"),
        DATABASE=os.environ.get("DATABASE_PATH", str(project_root / "data" / "munkaido.db")),
        TIMEZONE=os.environ.get("APP_TIMEZONE", "Europe/Budapest"),
        IMPORT_SEED_EXCEL=os.environ.get("IMPORT_SEED_EXCEL", "1") == "1",
        SEED_EXCEL_PATH=str(project_root / "seed" / "Kimutatas_a_ledolgozott_munkaidorol.xlsx"),
        ADMIN_LOGIN=os.environ.get("ADMIN_LOGIN", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        DEFAULT_USER_PASSWORD=os.environ.get("DEFAULT_USER_PASSWORD", ""),
        SEED_USER_LOGIN=os.environ.get("SEED_USER_LOGIN", ""),
        SEED_USER_DISPLAY_NAME=os.environ.get("SEED_USER_DISPLAY_NAME", "Importált felhasználó"),
        SEED_USER_PASSWORD=os.environ.get("SEED_USER_PASSWORD", ""),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    init_app(app)

    @app.template_filter("duration")
    def duration_filter(value):
        return format_duration(value)

    @app.template_filter("signed_duration")
    def signed_duration_filter(value):
        return format_duration(value, signed=True)

    @app.template_filter("clock")
    def clock_filter(value):
        return format_clock(value)

    @app.before_request
    def load_logged_in_user():
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            g.user = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)
            ).fetchone()
            if g.user is None:
                session.clear()

    def login_required(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            return view(**kwargs)

        return wrapped_view

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped_view(**kwargs):
            if not g.user["is_admin"]:
                abort(403)
            return view(**kwargs)

        return wrapped_view

    def local_now() -> datetime:
        return datetime.now(ZoneInfo(app.config["TIMEZONE"]))

    def parse_iso_date(value: str | None, default: date | None = None) -> date:
        if not value:
            if default is None:
                raise ValueError("Hiányzó dátum.")
            return default
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Érvénytelen dátum.") from exc

    def get_entry(user_id: int, day: date):
        return get_db().execute(
            "SELECT * FROM work_entries WHERE user_id = ? AND work_date = ?",
            (user_id, day.isoformat()),
        ).fetchone()

    def upsert_entry(user_id: int, day: date, **values):
        db = get_db()
        existing = get_entry(user_id, day)
        now = utc_now().isoformat()
        allowed = {
            "arrival_time", "departure_time", "break_seconds", "break_started_at",
            "day_type", "expected_seconds_override", "note", "source",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        if existing:
            if values:
                assignments = ", ".join(f"{key} = ?" for key in values)
                db.execute(
                    f"UPDATE work_entries SET {assignments}, updated_at = ? WHERE id = ?",
                    [*values.values(), now, existing["id"]],
                )
        else:
            defaults = {
                "arrival_time": None,
                "departure_time": None,
                "break_seconds": 0,
                "break_started_at": None,
                "day_type": "work",
                "expected_seconds_override": None,
                "note": "",
                "source": "manual",
            }
            defaults.update(values)
            db.execute(
                """
                INSERT INTO work_entries(
                    user_id, work_date, arrival_time, departure_time, break_seconds,
                    break_started_at, day_type, expected_seconds_override, note,
                    source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, day.isoformat(), defaults["arrival_time"], defaults["departure_time"],
                    defaults["break_seconds"], defaults["break_started_at"], defaults["day_type"],
                    defaults["expected_seconds_override"], defaults["note"], defaults["source"], now, now,
                ),
            )
        db.commit()
        return get_entry(user_id, day)

    def close_active_break(entry, end_utc: datetime | None = None) -> int:
        if not entry or not entry["break_started_at"]:
            return int(entry["break_seconds"] or 0) if entry else 0
        started = datetime.fromisoformat(entry["break_started_at"])
        ended = end_utc or utc_now()
        elapsed = max(0, int((ended - started).total_seconds()))
        return int(entry["break_seconds"] or 0) + elapsed

    def summary_for_year(user_id: int, year: int) -> dict:
        db = get_db()
        entries = db.execute(
            "SELECT * FROM work_entries WHERE user_id = ? AND work_date BETWEEN ? AND ? ORDER BY work_date",
            (user_id, f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
        months = [
            {"month": month, "name": MONTH_NAMES[month], "worked": 0, "expected": 0, "balance": 0, "days": 0}
            for month in range(1, 13)
        ]
        for entry in entries:
            day = date.fromisoformat(entry["work_date"])
            metrics = entry_metrics(db, user_id, day, entry)
            if not metrics.included:
                continue
            bucket = months[day.month - 1]
            bucket["worked"] += int(metrics.worked_seconds or 0)
            bucket["expected"] += int(metrics.expected_seconds or 0)
            bucket["balance"] += int(metrics.balance_seconds or 0)
            bucket["days"] += 1
        cumulative = 0
        maximum = max([abs(item["balance"]) for item in months] + [1])
        for item in months:
            cumulative += item["balance"]
            item["cumulative"] = cumulative
            item["bar_percent"] = round(abs(item["balance"]) / maximum * 48, 1)
        return {"year": year, "months": months, "balance": cumulative}

    def leave_summary(user_id: int, year: int) -> dict:
        db = get_db()
        allowance = db.execute(
            "SELECT allowance_half_days FROM leave_allowances WHERE user_id = ? AND year = ?",
            (user_id, year),
        ).fetchone()
        today = local_now().date().isoformat()
        rows = db.execute(
            """
            SELECT work_date, day_type FROM work_entries
            WHERE user_id = ? AND work_date BETWEEN ? AND ?
              AND day_type IN ('leave_full', 'leave_half_am', 'leave_half_pm')
            ORDER BY work_date
            """,
            (user_id, f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
        taken_units = 0
        planned_units = 0
        for row in rows:
            units = 2 if row["day_type"] == "leave_full" else 1
            if row["work_date"] <= today:
                taken_units += units
            else:
                planned_units += units
        total_units = int(allowance["allowance_half_days"]) if allowance else None
        return {
            "allowance": total_units / 2 if total_units is not None else None,
            "taken": taken_units / 2,
            "planned": planned_units / 2,
            "remaining": (total_units - taken_units - planned_units) / 2 if total_units is not None else None,
            "entries": rows,
        }

    def schedule_rows(user_id: int) -> list[dict]:
        rows = []
        for weekday in range(7):
            expected, arrival, departure = schedule_details(get_db(), user_id, weekday)
            rows.append({
                "weekday": weekday,
                "name": DAY_NAMES[weekday],
                "seconds": expected,
                "arrival": arrival,
                "departure": departure,
            })
        return rows

    def save_weekly_schedule(user_id: int) -> None:
        values = []
        for weekday in range(7):
            arrival_text = request.form.get(f"arrival_{weekday}", "").strip()
            departure_text = request.form.get(f"departure_{weekday}", "").strip()
            if not arrival_text and not departure_text:
                values.append((user_id, weekday, 0, None, None))
                continue
            if not arrival_text or not departure_text:
                raise ValueError(f"{DAY_NAMES[weekday]}: add meg az érkezést és a távozást is.")
            arrival = parse_hms(arrival_text)
            departure = parse_hms(departure_text)
            if arrival is None or departure is None or departure <= arrival:
                raise ValueError(f"{DAY_NAMES[weekday]}: a távozás legyen később az érkezésnél.")
            values.append((
                user_id,
                weekday,
                departure - arrival,
                format_clock(arrival),
                format_clock(departure),
            ))

        db = get_db()
        db.executemany(
            """
            INSERT INTO work_schedules(
                user_id, weekday, expected_seconds,
                default_arrival_time, default_departure_time
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, weekday) DO UPDATE SET
                expected_seconds = excluded.expected_seconds,
                default_arrival_time = excluded.default_arrival_time,
                default_departure_time = excluded.default_departure_time
            """,
            values,
        )
        db.commit()

    @app.get("/health")
    def health():
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if g.user else "login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            login_value = request.form.get("login", "").strip()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE login = ?", (login_value,)).fetchone()
            if not user or not user["active"] or not check_password_hash(user["password_hash"], password):
                flash("Hibás felhasználónév vagy jelszó.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(request.args.get("next") or url_for("dashboard"))
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        form_data = {"display_name": "", "email": ""}
        errors = {}
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            display_name = request.form.get("display_name", "").strip() or email
            password = request.form.get("password", "")
            form_data = {"display_name": request.form.get("display_name", "").strip(), "email": email}
            if not email or "@" not in email:
                errors["email"] = "Adj meg egy használható e-mail-címet, például nev@pelda.hu."
            if len(password) < 4:
                errors["password"] = "A jelszó legalább 4 karakter legyen."
            if not errors:
                db = get_db()
                try:
                    cursor = db.execute(
                        """
                        INSERT INTO users(login, display_name, password_hash, is_admin, active, created_at)
                        VALUES (?, ?, ?, 0, 1, ?)
                        """,
                        (email, display_name, generate_password_hash(password), utc_now().isoformat()),
                    )
                    add_default_schedule(db, int(cursor.lastrowid))
                    db.commit()
                    flash("A regisztráció elkészült. Most már bejelentkezhetsz.", "success")
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    db.rollback()
                    errors["email"] = "Ezzel az e-mail-címmel már létezik felhasználó."
                except sqlite3.Error:
                    db.rollback()
                    current_app.logger.exception("A regisztráció adatbázis-művelete sikertelen")
                    errors["form"] = "A fiókot most nem sikerült létrehozni. Próbáld újra, vagy jelezd az adminnak."
            if errors:
                flash("A fiók még nem jött létre. Javítsd a megjelölt mezőket.", "error")
        return render_template("register.html", form_data=form_data, errors=errors)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        today = local_now().date()
        try:
            selected_day = parse_iso_date(request.args.get("date"), today)
        except ValueError:
            selected_day = today
        entry = get_entry(g.user["id"], selected_day)
        metrics = entry_metrics(get_db(), g.user["id"], selected_day, entry)
        active_break_seconds = 0
        if entry and entry["break_started_at"]:
            active_break_seconds = max(
                0,
                int((utc_now() - datetime.fromisoformat(entry["break_started_at"])).total_seconds()),
            )
        year_summary = summary_for_year(g.user["id"], selected_day.year)
        month_data = year_summary["months"][selected_day.month - 1]
        leave_data = leave_summary(g.user["id"], selected_day.year)
        selected_week_start = selected_day - timedelta(days=selected_day.weekday())
        selected_week_end = selected_week_start + timedelta(days=6)
        return render_template(
            "dashboard.html",
            selected_day=selected_day,
            today=today,
            entry=entry,
            metrics=metrics,
            active_break_seconds=active_break_seconds,
            month_data=month_data,
            year_summary=year_summary,
            leave_data=leave_data,
            selected_week_start=selected_week_start,
            selected_week_end=selected_week_end,
            day_type_labels=DAY_TYPE_LABELS,
        )

    @app.post("/entry/save")
    @login_required
    def save_entry():
        today = local_now().date()
        try:
            day = parse_iso_date(request.form.get("work_date"), today)
            arrival_text = request.form.get("arrival_time", "").strip()
            departure_text = request.form.get("departure_time", "").strip()
            break_text = request.form.get("break_time", "00:00:00").strip()
            arrival = parse_hms(arrival_text)
            departure = parse_hms(departure_text)
            break_seconds = parse_hms(break_text, allow_over_24=True) or 0
            if arrival is not None and departure is not None:
                if departure < arrival:
                    raise ValueError("A távozás nem lehet korábbi az érkezésnél.")
                if break_seconds > departure - arrival:
                    raise ValueError("A kint töltött idő nem lehet hosszabb a bent töltött időnél.")
            existing = get_entry(g.user["id"], day)
            day_type = existing["day_type"] if existing and existing["day_type"].startswith("leave_half") else "work"
            upsert_entry(
                g.user["id"], day,
                arrival_time=format_clock(arrival) if arrival is not None else None,
                departure_time=format_clock(departure) if departure is not None else None,
                break_seconds=break_seconds,
                break_started_at=None,
                day_type=day_type,
                note=request.form.get("note", "").strip(),
                source="manual",
            )
            flash("A nap adatai elmentve.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("dashboard", date=request.form.get("work_date")))

    @app.post("/entry/arrival-now")
    @login_required
    def arrival_now():
        now = local_now()
        day = now.date()
        entry = get_entry(g.user["id"], day)
        if entry and entry["arrival_time"]:
            flash("A mai érkezés már rögzítve van.", "error")
        else:
            upsert_entry(
                g.user["id"], day,
                arrival_time=clock_now_text(now), departure_time=None,
                break_seconds=0, break_started_at=None, day_type="work", source="manual",
            )
            flash("Az érkezés rögzítve.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/entry/departure-now")
    @login_required
    def departure_now():
        now = local_now()
        day = now.date()
        entry = get_entry(g.user["id"], day)
        if not entry or not entry["arrival_time"]:
            flash("Előbb az érkezést kell rögzíteni.", "error")
        elif entry["departure_time"]:
            flash("A mai távozás már rögzítve van.", "error")
        else:
            break_seconds = close_active_break(entry)
            departure = clock_now_text(now)
            if parse_hms(departure) < parse_hms(entry["arrival_time"]):
                flash("Az alkalmazás jelenleg nem támogat éjszakán átnyúló műszakot.", "error")
                return redirect(url_for("dashboard"))
            upsert_entry(
                g.user["id"], day,
                departure_time=departure, break_seconds=break_seconds,
                break_started_at=None, source="manual",
            )
            flash("A távozás rögzítve, a nap lezárva.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/entry/pause-toggle")
    @login_required
    def pause_toggle():
        day = local_now().date()
        entry = get_entry(g.user["id"], day)
        if not entry or not entry["arrival_time"]:
            flash("Szünet csak a megérkezés után indítható.", "error")
        elif entry["departure_time"]:
            flash("A lezárt munkanapon nem indítható szünet.", "error")
        elif entry["break_started_at"]:
            total = close_active_break(entry)
            upsert_entry(g.user["id"], day, break_seconds=total, break_started_at=None)
            flash("A visszaérkezés rögzítve.", "success")
        else:
            upsert_entry(g.user["id"], day, break_started_at=utc_now().isoformat())
            flash("A kimenés rögzítve. A számláló elindult.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/entry/leave")
    @login_required
    def set_leave():
        try:
            day = parse_iso_date(request.form.get("work_date"), local_now().date())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))
        kind = request.form.get("kind")
        if kind not in ("leave_full", "leave_half_am", "leave_half_pm"):
            abort(400)
        existing = get_entry(g.user["id"], day)
        values = {"day_type": kind, "break_started_at": None, "source": "manual"}
        if kind == "leave_full":
            values.update(arrival_time=None, departure_time=None, break_seconds=0)
        elif not existing:
            values.update(arrival_time=None, departure_time=None, break_seconds=0)
        upsert_entry(g.user["id"], day, **values)
        flash("A szabadság rögzítve.", "success")
        return redirect(url_for("dashboard", date=day.isoformat()))

    @app.post("/entry/clear")
    @login_required
    def clear_entry():
        day = parse_iso_date(request.form.get("work_date"), local_now().date())
        existing = get_entry(g.user["id"], day)
        expected_override = existing["expected_seconds_override"] if existing else None
        upsert_entry(
            g.user["id"], day,
            arrival_time=None, departure_time=None, break_seconds=0, break_started_at=None,
            day_type="work", expected_seconds_override=expected_override,
            note=(existing["note"] if existing else ""), source="manual",
        )
        flash("A nap időadatai kiürítve.", "success")
        return redirect(url_for("dashboard", date=day.isoformat()))

    @app.post("/entry/fill-week")
    @login_required
    def fill_week():
        try:
            selected_day = parse_iso_date(request.form.get("selected_date"), local_now().date())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

        today = local_now().date()
        week_start = selected_day - timedelta(days=selected_day.weekday())
        week_end = min(week_start + timedelta(days=6), today)
        if week_end < week_start:
            flash("Jövőbeli hét napjai nem tölthetők ki automatikusan.", "error")
            return redirect(url_for("dashboard", date=selected_day.isoformat()))

        filled = 0
        skipped_existing = 0
        skipped_nonwork = 0
        skipped_unconfigured = 0
        day = week_start
        while day <= week_end:
            entry = get_entry(g.user["id"], day)
            if entry and (
                entry["day_type"] != "work"
                or entry["arrival_time"]
                or entry["departure_time"]
                or entry["break_started_at"]
            ):
                skipped_existing += 1
                day += timedelta(days=1)
                continue

            expected, arrival, departure, _label = calendar_schedule_details(
                get_db(), g.user["id"], day
            )
            if entry and entry["expected_seconds_override"] is not None:
                expected = int(entry["expected_seconds_override"])
                if arrival and expected > 0:
                    arrival_seconds = parse_hms(arrival)
                    calculated_departure = int(arrival_seconds or 0) + expected
                    departure = (
                        format_clock(calculated_departure)
                        if calculated_departure < 24 * 3600
                        else None
                    )
            if expected <= 0:
                skipped_nonwork += 1
            elif not arrival or not departure:
                skipped_unconfigured += 1
            else:
                upsert_entry(
                    g.user["id"],
                    day,
                    arrival_time=arrival,
                    departure_time=departure,
                    break_seconds=0,
                    break_started_at=None,
                    day_type="work",
                    source="weekly-auto-fill",
                )
                filled += 1
            day += timedelta(days=1)

        details = [f"{filled} nap kitöltve"]
        if skipped_existing:
            details.append(f"{skipped_existing} meglévő nap változatlan")
        if skipped_nonwork:
            details.append(f"{skipped_nonwork} szabad/ünnepnap kihagyva")
        if skipped_unconfigured:
            details.append(f"{skipped_unconfigured} beosztás nélküli nap kihagyva")
        flash("Heti pótlás kész: " + ", ".join(details) + ".", "success")
        return redirect(url_for("dashboard", date=selected_day.isoformat()))

    @app.get("/history")
    @login_required
    def history():
        today = local_now().date()
        raw_month = request.args.get("month", today.strftime("%Y-%m"))
        try:
            year, month = map(int, raw_month.split("-"))
            if month not in range(1, 13):
                raise ValueError
        except ValueError:
            year, month = today.year, today.month
        db = get_db()
        entries = {
            row["work_date"]: row
            for row in db.execute(
                "SELECT * FROM work_entries WHERE user_id = ? AND work_date BETWEEN ? AND ?",
                (g.user["id"], f"{year}-{month:02d}-01", f"{year}-{month:02d}-31"),
            ).fetchall()
        }
        rows = []
        for day in iter_month_days(year, month):
            entry = entries.get(day.isoformat())
            metrics = entry_metrics(db, g.user["id"], day, entry)
            if entry and entry["day_type"] in ("leave_full", "leave_half_am", "leave_half_pm", "off"):
                status = DAY_TYPE_LABELS[entry["day_type"]]
                status_class = "neutral"
            elif metrics.complete:
                status = "Lezárt"
                status_class = "success"
            elif entry and entry["arrival_time"]:
                status = "Nincs lezárva"
                status_class = "warning"
            elif day < today and (metrics.expected_seconds or 0) > 0:
                status = "Hiányzó adat"
                status_class = "danger"
            else:
                status = metrics.calendar_label or "Nincs adat"
                status_class = "muted"
            rows.append({"day": day, "entry": entry, "metrics": metrics, "status": status, "status_class": status_class})
        previous = month_shift(year, month, -1)
        following = month_shift(year, month, 1)
        return render_template(
            "history.html", year=year, month=month, month_name=MONTH_NAMES[month],
            rows=rows, previous=f"{previous[0]}-{previous[1]:02d}", next_month=f"{following[0]}-{following[1]:02d}",
        )

    @app.get("/stats")
    @login_required
    def stats():
        year = request.args.get("year", type=int) or local_now().year
        return render_template(
            "stats.html",
            summary=summary_for_year(g.user["id"], year),
            leave_data=leave_summary(g.user["id"], year),
        )

    @app.route("/leave", methods=["GET", "POST"])
    @login_required
    def leave():
        year = request.values.get("year", type=int) or local_now().year
        if request.method == "POST":
            try:
                allowance = float(request.form.get("allowance", "0").replace(",", "."))
                if allowance < 0 or allowance * 2 != int(allowance * 2):
                    raise ValueError
                get_db().execute(
                    """
                    INSERT INTO leave_allowances(user_id, year, allowance_half_days)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, year) DO UPDATE SET allowance_half_days = excluded.allowance_half_days
                    """,
                    (g.user["id"], year, int(allowance * 2)),
                )
                get_db().commit()
                flash("A szabadságkeret elmentve.", "success")
            except ValueError:
                flash("A keret csak egész vagy fél nap lehet, például 25 vagy 25,5.", "error")
            return redirect(url_for("leave", year=year))
        return render_template("leave.html", year=year, leave_data=leave_summary(g.user["id"], year))

    @app.route("/schedule", methods=["GET", "POST"])
    @login_required
    def my_schedule():
        if request.method == "POST":
            try:
                save_weekly_schedule(g.user["id"])
                flash("A saját heti beosztásod elmentve.", "success")
                return redirect(url_for("my_schedule"))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template(
            "admin_schedule.html",
            selected_user=g.user,
            schedule=schedule_rows(g.user["id"]),
            own_schedule=True,
        )

    @app.route("/settings/password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            repeated = request.form.get("new_password_again", "")
            if not check_password_hash(g.user["password_hash"], current):
                flash("A jelenlegi jelszó hibás.", "error")
            elif len(new) < 4:
                flash("Az új jelszó legalább 4 karakter legyen.", "error")
            elif new != repeated:
                flash("A két új jelszó nem egyezik.", "error")
            else:
                get_db().execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new), g.user["id"]),
                )
                get_db().commit()
                flash("A jelszó megváltozott.", "success")
                return redirect(url_for("dashboard"))
        return render_template("change_password.html")

    @app.get("/export.xlsx")
    @login_required
    def export_xlsx():
        raw_year = request.args.get("year", str(local_now().year))
        year = None if raw_year == "all" else int(raw_year)
        output = build_export(get_db(), g.user, year)
        suffix = "minden-adat" if year is None else str(year)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"munkaido-{suffix}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/import", methods=["GET", "POST"])
    @login_required
    def import_xlsx():
        import_errors: list[str] = []
        selected_mode = request.form.get("mode", "skip")
        if request.method == "POST":
            upload = request.files.get("file")
            if selected_mode not in ("skip", "overwrite"):
                abort(400)
            if not upload or not upload.filename:
                import_errors.append("Válassz ki egy .xlsx fájlt.")
            elif not upload.filename.lower().endswith(".xlsx"):
                import_errors.append("Csak .xlsx formátumú Excel-fájl tölthető fel.")
            else:
                db = get_db()
                try:
                    result = import_export_workbook(
                        db,
                        g.user["id"],
                        upload.stream,
                        overwrite=selected_mode == "overwrite",
                    )
                    db.commit()
                    details = [f'{result["created"]} új nap importálva']
                    if result["updated"]:
                        details.append(f'{result["updated"]} meglévő nap felülírva')
                    if result["skipped"]:
                        details.append(f'{result["skipped"]} meglévő nap kihagyva')
                    allowance_changes = result["allowances_created"] + result["allowances_updated"]
                    if allowance_changes:
                        details.append(f"{allowance_changes} szabadságkeret átvéve")
                    if result["allowances_skipped"]:
                        details.append(
                            f'{result["allowances_skipped"]} meglévő szabadságkeret kihagyva'
                        )
                    flash("Excel-import kész: " + ", ".join(details) + ".", "success")
                    return redirect(url_for("import_xlsx"))
                except WorkbookImportError as exc:
                    db.rollback()
                    import_errors = exc.errors
                except sqlite3.Error:
                    db.rollback()
                    current_app.logger.exception("Az Excel-import adatbázis-művelete sikertelen")
                    import_errors = [
                        "Az adatokat most nem sikerült elmenteni. Az adatbázis nem változott."
                    ]
        return render_template(
            "import.html",
            import_errors=import_errors,
            selected_mode=selected_mode,
        )

    @app.get("/admin/users")
    @admin_required
    def admin_users():
        users = get_db().execute("SELECT * FROM users ORDER BY is_admin DESC, login").fetchall()
        return render_template("admin_users.html", users=users)

    @app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_edit_user(user_id: int):
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)

        form_data = {
            "login": user["login"],
            "display_name": user["display_name"],
        }
        errors: dict[str, str] = {}
        if request.method == "POST":
            form_data = {
                "login": request.form.get("login", "").strip(),
                "display_name": request.form.get("display_name", "").strip(),
            }
            if not form_data["login"]:
                errors["login"] = "A felhasználónév nem lehet üres."
            elif len(form_data["login"]) > 254:
                errors["login"] = "A felhasználónév legfeljebb 254 karakter lehet."
            if not form_data["display_name"]:
                errors["display_name"] = "A megjelenített név nem lehet üres."
            elif len(form_data["display_name"]) > 100:
                errors["display_name"] = "A megjelenített név legfeljebb 100 karakter lehet."

            if not errors:
                try:
                    db.execute(
                        "UPDATE users SET login = ?, display_name = ? WHERE id = ?",
                        (form_data["login"], form_data["display_name"], user_id),
                    )
                    db.commit()
                    flash("A felhasználó adatai frissültek.", "success")
                    return redirect(url_for("admin_users"))
                except sqlite3.IntegrityError:
                    db.rollback()
                    errors["login"] = "Ez a felhasználónév már használatban van."

        return render_template(
            "admin_user_edit.html",
            selected_user=user,
            form_data=form_data,
            errors=errors,
        )

    @app.post("/admin/users/<int:user_id>/reset-password")
    @admin_required
    def admin_reset_password(user_id: int):
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)
        default_password = app.config.get("DEFAULT_USER_PASSWORD", "")
        if not default_password:
            flash(
                "A jelszó-visszaállításhoz előbb add meg a DEFAULT_USER_PASSWORD értékét a szerver .env fájljában.",
                "error",
            )
            return redirect(url_for("admin_users"))
        get_db().execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(default_password), user_id),
        )
        get_db().commit()
        flash(f"{user['login']} jelszava visszaállt a beállított alapértelmezett jelszóra.", "success")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<int:user_id>/toggle-active")
    @admin_required
    def admin_toggle_active(user_id: int):
        if user_id == g.user["id"]:
            flash("A saját admin fiókodat nem tilthatod le.", "error")
        else:
            get_db().execute("UPDATE users SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
            get_db().commit()
            flash("A felhasználó állapota módosult.", "success")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<int:user_id>/delete")
    @admin_required
    def admin_delete_user(user_id: int):
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)
        if user_id == g.user["id"]:
            flash("A jelenleg használt admin fiók nem törölhető.", "error")
            return redirect(url_for("admin_users"))

        login = user["login"]
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash(f"{login} és minden hozzá tartozó adat véglegesen törölve lett.", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/schedule", methods=["GET", "POST"])
    @admin_required
    def admin_schedule(user_id: int):
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)
        if request.method == "POST":
            try:
                save_weekly_schedule(user_id)
                flash("A heti munkaidő-beosztás elmentve.", "success")
                return redirect(url_for("admin_schedule", user_id=user_id))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template(
            "admin_schedule.html",
            selected_user=user,
            schedule=schedule_rows(user_id),
            own_schedule=False,
        )

    @app.route("/admin/calendar", methods=["GET", "POST"])
    @admin_required
    def admin_calendar():
        db = get_db()
        year = request.values.get("year", type=int) or local_now().year
        if request.method == "POST":
            try:
                day = parse_iso_date(request.form.get("work_date"))
                kind = request.form.get("kind")
                if kind in ("holiday", "rest_day", "transferred_workday", "normal"):
                    source = request.form.get("source_date") or None
                    if kind == "transferred_workday" and not source:
                        raise ValueError("Áthelyezett munkanapnál add meg az eredeti napot is.")
                    db.execute(
                        """
                        INSERT INTO calendar_overrides(work_date, kind, source_date, label)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(work_date) DO UPDATE SET
                          kind = excluded.kind, source_date = excluded.source_date, label = excluded.label
                        """,
                        (
                            day.isoformat(), kind, source,
                            request.form.get("label", "").strip() or ("Normál nap" if kind == "normal" else ""),
                        ),
                    )
                else:
                    raise ValueError("Érvénytelen naptípus.")
                db.commit()
                flash("A munkanaptár frissült.", "success")
            except ValueError as exc:
                flash(str(exc), "error")
            return redirect(url_for("admin_calendar", year=year))
        rows = db.execute(
            "SELECT * FROM calendar_overrides WHERE work_date BETWEEN ? AND ? ORDER BY work_date",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
        return render_template("admin_calendar.html", year=year, rows=rows)

    return app

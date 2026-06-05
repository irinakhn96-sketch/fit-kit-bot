"""
База данных — хранение результатов тренировок и настроек
"""

import aiosqlite
from datetime import date
from typing import Optional

DB_PATH = "workout_bot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workout_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise TEXT NOT NULL,
                weight REAL DEFAULT 0,
                reps INTEGER DEFAULT 0,
                sets INTEGER DEFAULT 0,
                done_only INTEGER DEFAULT 0,
                workout_date TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Миграция — добавить done_only если нет
        try:
            await db.execute("ALTER TABLE workout_logs ADD COLUMN done_only INTEGER DEFAULT 0")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('cycle_day', '8')
        """)
        await db.commit()


async def save_workout_log(exercise: str, weight: float, reps: int, sets: int,
                           workout_date: date, done_only: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO workout_logs (exercise, weight, reps, sets, done_only, workout_date)
               VALUES (?,?,?,?,?,?)""",
            (exercise, weight, reps, sets, 1 if done_only else 0, workout_date.isoformat())
        )
        await db.commit()


async def get_recent_logs(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM workout_logs ORDER BY workout_date DESC, id DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_workout_history() -> list[dict]:
    """История по датам"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM workout_logs
               ORDER BY workout_date DESC, id DESC
               LIMIT 100"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_progress_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM workout_logs")
        row = await cursor.fetchone()
        total = row[0] if row else 0

        cursor = await db.execute("SELECT MIN(workout_date) as first FROM workout_logs")
        row = await cursor.fetchone()
        first_date = row[0] if row else None

        cursor = await db.execute(
            """SELECT exercise, MAX(weight) as best FROM workout_logs
               WHERE weight > 0
               GROUP BY exercise ORDER BY best DESC LIMIT 10"""
        )
        rows = await cursor.fetchall()
        best_weights = {row[0]: row[1] for row in rows}

    return {
        "total_logs": total,
        "first_date": first_date,
        "best_weights": best_weights,
    }


async def get_cycle_day() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'cycle_day'")
        row = await cursor.fetchone()
        return int(row[0]) if row else 8


async def set_cycle_day(day: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('cycle_day', ?)",
            (str(day),)
        )
        await db.commit()


# ═══════════════════════════════════════════
# ТРЕКЕР ПИТАНИЯ
# ═══════════════════════════════════════════

async def init_food_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS food_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_type TEXT NOT NULL,
                food_name TEXT NOT NULL,
                calories REAL DEFAULT 0,
                protein REAL DEFAULT 0,
                fat REAL DEFAULT 0,
                carbs REAL DEFAULT 0,
                grams REAL DEFAULT 0,
                log_date TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def save_food_log(meal_type: str, food_name: str, calories: float,
                        protein: float, fat: float, carbs: float,
                        grams: float, log_date: date):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO food_logs (meal_type, food_name, calories, protein, fat, carbs, grams, log_date)
               VALUES (?,?,?,?,?,?,?,?)""",
            (meal_type, food_name, calories, protein, fat, carbs, grams, log_date.isoformat())
        )
        await db.commit()


async def get_food_logs_today(log_date: date = None) -> list[dict]:
    if log_date is None:
        log_date = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM food_logs WHERE log_date = ? ORDER BY id ASC",
            (log_date.isoformat(),)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_food_totals_today(log_date: date = None) -> dict:
    logs = await get_food_logs_today(log_date)
    totals = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "entries": len(logs)}
    for log in logs:
        totals["calories"] += log["calories"]
        totals["protein"] += log["protein"]
        totals["fat"] += log["fat"]
        totals["carbs"] += log["carbs"]
    return totals


async def delete_last_food_log(log_date: date = None) -> bool:
    if log_date is None:
        log_date = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM food_logs WHERE log_date = ? ORDER BY id DESC LIMIT 1",
            (log_date.isoformat(),)
        )
        row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM food_logs WHERE id = ?", (row[0],))
            await db.commit()
            return True
    return False


# ═══════════════════════════════════════════
# ВЕС ТЕЛА
# ═══════════════════════════════════════════

async def init_bodyweight_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS body_weight (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weight REAL NOT NULL,
                log_date TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def save_body_weight(weight: float, log_date: date, note: str = ''):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO body_weight (weight, log_date, note) VALUES (?,?,?)",
            (weight, log_date.isoformat(), note)
        )
        await db.commit()


async def get_body_weight_history(limit: int = 30) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM body_weight ORDER BY log_date DESC, id DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_exercise_history(exercise_name: str, limit: int = 10) -> list[dict]:
    """История результатов по конкретному упражнению"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM workout_logs
               WHERE exercise LIKE ? AND weight > 0
               ORDER BY workout_date DESC, id DESC LIMIT ?""",
            (f"%{exercise_name[:20]}%", limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_exercises_with_logs() -> list[str]:
    """Все упражнения у которых есть записи с весом"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT DISTINCT exercise FROM workout_logs
               WHERE weight > 0 ORDER BY exercise"""
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

"""
Telegram бот для тренировок Ирины
Запуск: python bot.py
Требования: pip install aiogram aiosqlite
"""

import asyncio
import logging
import os
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import db
from data import NUTRITION, get_today_workout, get_cycle_phase
from schedule import get_current_workouts, get_current_block, get_block_info

# ═══════════════════════════════════════════
# Настройка
# ═══════════════════════════════════════════

import os
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ═══════════════════════════════════════════
# FSM состояния
# ═══════════════════════════════════════════

class LogExercise(StatesGroup):
    entering_weight = State()
    entering_reps = State()
    entering_sets = State()

class SetCycleDay(StatesGroup):
    entering_day = State()


# ═══════════════════════════════════════════
# Клавиатуры
# ═══════════════════════════════════════════

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏋️ Тренировка сегодня"), KeyboardButton(text="📋 История тренировок")],
            [KeyboardButton(text="🍽 Дневник питания"), KeyboardButton(text="⚖️ Мой вес")],
            [KeyboardButton(text="📈 Прогресс упражнений"), KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="🥗 Питание"), KeyboardButton(text="🌸 Фаза цикла")],
        ],
        resize_keyboard=True
    )

def workout_day_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="День А — Ноги/Квадрицепс", callback_data="workout_A")],
        [InlineKeyboardButton(text="День Б — Верх/Спина", callback_data="workout_B")],
        [InlineKeyboardButton(text="День В — Ягодицы/Задняя поверхность", callback_data="workout_C")],
    ])

def exercise_keyboard(ex_name: str, ex_index: int, day: str, done: bool = False):
    """Кнопки под каждым упражнением"""
    safe_name = ex_name[:25]
    if done:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выполнено!", callback_data="noop")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выполнил(а)", callback_data=f"done_{day}_{ex_index}_{safe_name}"),
            InlineKeyboardButton(text="📝 Записать вес", callback_data=f"log_{day}_{ex_index}_{safe_name}"),
        ],
    ])

def nutrition_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 КБЖУ на день", callback_data="nutrition_kbzhu")],
        [InlineKeyboardButton(text="✅ Можно есть", callback_data="nutrition_ok")],
        [InlineKeyboardButton(text="❌ Лучше избегать", callback_data="nutrition_avoid")],
        [InlineKeyboardButton(text="🍽️ Примеры приёмов пищи", callback_data="nutrition_meals")],
    ])


# ═══════════════════════════════════════════
# /start
# ═══════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await db.init_db()
    text = (
        "Привет, Ирина! 💪\n\n"
        "Я твой персональный бот для тренировок.\n\n"
        "Что умею:\n"
        "• Показывать план тренировки по упражнениям\n"
        "• Отмечать выполненные упражнения\n"
        "• Записывать вес и повторения прямо во время тренировки\n"
        "• Учитывать фазу цикла и менять блоки каждые 2 недели\n\n"
        "Выбирай что нужно 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())


# ═══════════════════════════════════════════
# Тренировка — показ упражнений по одному
# ═══════════════════════════════════════════

@dp.message(F.text == "🏋️ Тренировка сегодня")
async def today_workout(message: types.Message):
    cycle_day = await db.get_cycle_day()
    phase, phase_note = get_cycle_phase(cycle_day)
    block_info = get_block_info()

    text = (
        f"📅 {date.today().strftime('%d.%m.%Y')}\n"
        f"🌸 Фаза цикла: {phase} (день {cycle_day})\n"
        f"💡 {phase_note}\n\n"
        f"📦 {block_info['name']} ({block_info['weeks']})\n"
        f"До смены блока: {block_info['days_left']} дн. ({block_info['next_change']})\n\n"
        f"Выбери тренировку на сегодня:"
    )
    await message.answer(text, reply_markup=workout_day_keyboard())


@dp.callback_query(F.data.startswith("workout_"))
async def show_workout(callback: types.CallbackQuery):
    day = callback.data.split("_")[1]  # A, B или C
    workouts = get_current_workouts()
    workout = workouts[day]
    block_info = get_block_info()

    # Шапка тренировки
    header = (
        f"🏋️ {workout['name']}\n"
        f"({block_info['name']})\n\n"
        f"🔥 Разминка: эллипс/дорожка 10 мин\n"
        f"Повороты головы, вращение плеч, наклоны корпуса,\n"
        f"приседания без веса, гиперэкстензия — по 15 повт\n\n"
        f"Поехали! Отмечай каждое упражнение после выполнения 👇"
    )
    await callback.message.answer(header)

    # Каждое упражнение отдельным сообщением с кнопками
    for i, ex in enumerate(workout['exercises']):
        text = f"{i+1}. {ex['name']}\n"
        text += f"📌 {ex['sets']} x {ex['reps']}"
        if ex.get('weight'):
            text += f" | Вес: {ex['weight']}"
        text += "\n"
        if ex.get('tip'):
            text += f"💡 {ex['tip']}\n"
        if ex.get('video'):
            text += f"🎥 {ex['video']}\n"

        kb = exercise_keyboard(ex['name'], i, day)
        await callback.message.answer(text, reply_markup=kb)

    await callback.message.answer(
        "Удачной тренировки! 💪\nОтмечай упражнения и записывай веса по ходу.",
        reply_markup=main_keyboard()
    )
    await callback.answer()


# ═══════════════════════════════════════════
# Отметить упражнение выполненным
# ═══════════════════════════════════════════

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    parts = callback.data.split("_", 3)
    # done_DAY_INDEX_NAME
    day = parts[1]
    ex_name = parts[3] if len(parts) > 3 else "упражнение"

    await db.save_workout_log(
        exercise=ex_name,
        weight=0,
        reps=0,
        sets=0,
        workout_date=date.today(),
        done_only=True
    )

    # Обновляем кнопку
    new_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнено!", callback_data="noop")],
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        pass
    await callback.answer("✅ Отмечено!")


# ═══════════════════════════════════════════
# Записать вес/результат прямо из тренировки
# ═══════════════════════════════════════════

@dp.callback_query(F.data.startswith("log_"))
async def log_from_workout(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 3)
    # log_DAY_INDEX_NAME
    ex_name = parts[3] if len(parts) > 3 else "упражнение"
    day = parts[1]
    ex_index = parts[2]

    await state.update_data(exercise=ex_name, day=day, ex_index=ex_index,
                            msg_id=callback.message.message_id)
    await callback.message.answer(
        f"📝 {ex_name}\n\nСколько кг? (если без веса — напиши 0)"
    )
    await state.set_state(LogExercise.entering_weight)
    await callback.answer()


@dp.message(LogExercise.entering_weight)
async def log_weight(message: types.Message, state: FSMContext):
    try:
        weight = float(message.text.replace(",", "."))
        await state.update_data(weight=weight)
        await message.answer("Сколько повторений?")
        await state.set_state(LogExercise.entering_reps)
    except ValueError:
        await message.answer("Введи число, например: 35 или 0")


@dp.message(LogExercise.entering_reps)
async def log_reps(message: types.Message, state: FSMContext):
    try:
        reps = int(message.text.strip())
        await state.update_data(reps=reps)
        await message.answer("Сколько подходов?")
        await state.set_state(LogExercise.entering_sets)
    except ValueError:
        await message.answer("Введи число, например: 3")


@dp.message(LogExercise.entering_sets)
async def log_sets(message: types.Message, state: FSMContext):
    try:
        sets = int(message.text.strip())
        data = await state.get_data()

        await db.save_workout_log(
            exercise=data['exercise'],
            weight=data['weight'],
            reps=data['reps'],
            sets=sets,
            workout_date=date.today()
        )

        weight_str = f"{data['weight']} кг x " if data['weight'] > 0 else ""
        text = (
            f"✅ Записано!\n\n"
            f"💪 {data['exercise']}\n"
            f"📊 {weight_str}{data['reps']} повт x {sets} подходов\n"
            f"📅 {date.today().strftime('%d.%m.%Y')}"
        )
        await message.answer(text, reply_markup=main_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("Введи число, например: 4")


@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()


# ═══════════════════════════════════════════
# Фаза цикла
# ═══════════════════════════════════════════

@dp.message(F.text == "🌸 Фаза цикла")
async def cycle_info(message: types.Message):
    cycle_day = await db.get_cycle_day()
    phase, note = get_cycle_phase(cycle_day)

    text = (
        f"🌸 Менструальный цикл\n\n"
        f"День цикла: {cycle_day} из 28\n"
        f"Фаза: {phase}\n\n"
        f"💡 {note}\n\n"
        f"Режим тренировок по фазам:\n"
        f"🔴 Менструация (1-7): -20-30% веса, можно пропустить\n"
        f"🟢 Фолликулярная (8-13): Максимум нагрузки, пробуй новые веса!\n"
        f"🟡 Овуляция (14-16): Пик силы, следи за техникой\n"
        f"🟠 Лютеиновая (17-28): Постепенно снижай к концу\n\n"
        f"Хочешь обновить день цикла? Напиши /setcycle"
    )
    await message.answer(text)


@dp.message(Command("setcycle"))
async def set_cycle(message: types.Message, state: FSMContext):
    await message.answer("Введи текущий день цикла (число от 1 до 28):")
    await state.set_state(SetCycleDay.entering_day)


@dp.message(SetCycleDay.entering_day)
async def save_cycle_day(message: types.Message, state: FSMContext):
    try:
        day = int(message.text.strip())
        if 1 <= day <= 28:
            await db.set_cycle_day(day)
            phase, note = get_cycle_phase(day)
            await message.answer(f"Сохранено! День {day} — фаза {phase}\n💡 {note}")
            await state.clear()
        else:
            await message.answer("Введи число от 1 до 28")
    except ValueError:
        await message.answer("Введи число, например: 8")


# ═══════════════════════════════════════════
# Питание
# ═══════════════════════════════════════════

@dp.message(F.text == "🥗 Питание")
async def nutrition_menu(message: types.Message):
    await message.answer("Питание и продукты 🥗", reply_markup=nutrition_keyboard())


@dp.callback_query(F.data == "nutrition_kbzhu")
async def show_kbzhu(callback: types.CallbackQuery):
    text = (
        "📊 Дневная норма КБЖУ\n\n"
        "Твои параметры: 164 см, 53 кг\n"
        "Цель: минус 5 кг жира, просушка ног\n\n"
        "Норма на день (дефицит):\n"
        "Калории: ~1450-1550 ккал\n"
        "Белок: 110-120 г\n"
        "Жиры: 45-55 г\n"
        "Углеводы: 130-150 г\n\n"
        "В тренировочный день:\n"
        "Калории: ~1600-1700 ккал\n"
        "Белок: 120-130 г\n"
        "Жиры: 50-60 г\n"
        "Углеводы: 160-180 г\n\n"
        "Основная часть углеводов - до и после тренировки"
    )
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "nutrition_ok")
async def show_ok_foods(callback: types.CallbackQuery):
    text = (
        "✅ Продукты с низкой реакцией - можно свободно:\n\n"
        "Белок:\n"
        "Курица, индейка, кролик, говядина\n"
        "Треска, тунец, лосось, форель, креветки\n\n"
        "Углеводы:\n"
        "Гречка, рис, рожь, овёс, перловка\n\n"
        "Овощи:\n"
        "Картофель, помидор, огурец, морковь\n"
        "Свёкла, шпинат, брокколи, авокадо\n\n"
        "Фрукты:\n"
        "Яблоко, персик, черника, клубника, груша, слива\n\n"
        "Молочное:\n"
        "Яйцо перепелиное, сыр швейцарский, молоко козье"
    )
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "nutrition_avoid")
async def show_avoid_foods(callback: types.CallbackQuery):
    text = (
        "❌ Продукты с высокой реакцией - лучше избегать:\n\n"
        "Арахис (349)\n"
        "Дрожжи пивные (466) и пекарские (311)\n"
        "Масло сливочное (244)\n"
        "Брынза овечья (314), йогурт (315)\n"
        "Коровье молоко (167), сыворотка (150)\n"
        "Кальмар (206), кукуруза (165)\n"
        "Перец чёрный (298), чили (267)\n"
        "Мёд (217), горчица (217)\n\n"
        "Числа - уровень реакции по тесту ImmunoHealth"
    )
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "nutrition_meals")
async def show_meals(callback: types.CallbackQuery):
    text = (
        "Примеры приёмов пищи\n\n"
        "Завтрак:\n"
        "Овсянка на козьем молоке 150г + яблоко + 3 перепелиных яйца\n"
        "~350 ккал | Б:18г | Ж:12г | У:42г\n\n"
        "Перекус:\n"
        "Форель 100г + огурец или яблоко\n"
        "~200 ккал\n\n"
        "Обед:\n"
        "Куриная грудка 150г + гречка 100г (сухой вес) + брокколи\n"
        "~450 ккал | Б:42г | Ж:6г | У:48г\n\n"
        "До тренировки (за 1-1.5 ч):\n"
        "Рис 80г (сухой) + индейка 120г\n"
        "~400 ккал\n\n"
        "После тренировки:\n"
        "Лосось 150г + картофель 150г + шпинат\n"
        "~400 ккал\n\n"
        "Ужин:\n"
        "Говядина 130г + овощи тушёные\n"
        "~300 ккал"
    )
    await callback.message.answer(text)
    await callback.answer()


# ═══════════════════════════════════════════
# История и прогресс
# ═══════════════════════════════════════════

@dp.message(F.text == "⚖️ Мои веса")
async def show_my_weights(message: types.Message):
    logs = await db.get_recent_logs(limit=15)

    if not logs:
        await message.answer(
            "Пока нет записанных результатов.\n"
            "Нажми кнопку '📝 Записать вес' под упражнением во время тренировки!"
        )
        return

    text = "⚖️ Последние записи:\n\n"
    for log in logs:
        if log['weight'] and log['weight'] > 0:
            text += f"📅 {log['date']} | {log['exercise']}\n"
            text += f"   {log['weight']} кг x {log['reps']} повт x {log['sets']} подх\n\n"
        else:
            text += f"📅 {log['date']} | {log['exercise']} ✅\n\n"

    await message.answer(text)


@dp.message(F.text == "📋 История тренировок")
async def show_history(message: types.Message):
    logs = await db.get_workout_history()

    if not logs:
        await message.answer("Пока нет записей. Начни тренировку и отмечай упражнения!")
        return

    # Группируем по датам
    by_date = {}
    for log in logs:
        d = log['date']
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(log)

    text = "📋 История тренировок:\n\n"
    for d in list(by_date.keys())[:5]:  # последние 5 дней
        entries = by_date[d]
        text += f"📅 {d} — {len(entries)} упражнений\n"
        for log in entries[:4]:
            if log['weight'] and log['weight'] > 0:
                text += f"  • {log['exercise']}: {log['weight']}кг x {log['reps']}повт x {log['sets']}подх\n"
            else:
                text += f"  • {log['exercise']} ✅\n"
        if len(entries) > 4:
            text += f"  ...и ещё {len(entries)-4}\n"
        text += "\n"

    await message.answer(text)


@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message):
    stats = await db.get_progress_stats()

    text = "📊 Твой прогресс\n\n"
    text += f"🏋️ Всего записей: {stats['total_logs']}\n"
    text += f"📅 Первая запись: {stats['first_date'] or 'нет данных'}\n\n"

    if stats['best_weights']:
        text += "🏆 Лучшие веса:\n"
        for ex, weight in list(stats['best_weights'].items())[:8]:
            if weight > 0:
                text += f"• {ex}: {weight} кг\n"

    await message.answer(text)


# ═══════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════

async def on_startup(app):
    await db.init_db()
    await db.init_food_db()
    await db.init_bodyweight_db()
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if webhook_url:
        await bot.set_webhook(f"{webhook_url}/webhook")
        logger.info(f"Webhook set: {webhook_url}/webhook")
    logger.info("Бот запущен!")


async def on_shutdown(app):
    await bot.delete_webhook()


def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    PORT = int(os.getenv("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════
# ТРЕКЕР ПИТАНИЯ
# ═══════════════════════════════════════════

from food_data import FOODS, MEAL_TYPES, MEAL_EMOJI, find_food, calc_kbzhu, get_food_list
import db as _db


class AddFood(StatesGroup):
    choosing_meal = State()
    entering_food = State()
    entering_grams = State()


def food_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить еду", callback_data="food_add")],
        [InlineKeyboardButton(text="📊 Сводка за сегодня", callback_data="food_today")],
        [InlineKeyboardButton(text="📋 Список продуктов", callback_data="food_list")],
        [InlineKeyboardButton(text="🗑 Удалить последнюю запись", callback_data="food_delete_last")],
    ])


def meal_type_keyboard():
    buttons = []
    for label, code in MEAL_TYPES.items():
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"meal_{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(F.text == "🍽 Дневник питания")
async def food_diary(message: types.Message):
    totals = await db.get_food_totals_today()
    norm_cal = 1500
    norm_p = 115
    norm_f = 50
    norm_c = 140

    bar_cal = min(int(totals['calories'] / norm_cal * 10), 10)
    bar_p   = min(int(totals['protein']  / norm_p   * 10), 10)

    text = (
        f"🍽 Дневник питания — {date.today().strftime('%d.%m.%Y')}\n\n"
        f"Калории:  {totals['calories']:.0f} / {norm_cal} ккал  {'█' * bar_cal}{'░' * (10 - bar_cal)}\n"
        f"Белки:    {totals['protein']:.1f} / {norm_p} г  {'█' * bar_p}{'░' * (10 - bar_p)}\n"
        f"Жиры:     {totals['fat']:.1f} / {norm_f} г\n"
        f"Углеводы: {totals['carbs']:.1f} / {norm_c} г\n\n"
        f"Записей за день: {totals['entries']}"
    )
    await message.answer(text, reply_markup=food_menu_keyboard())


@dp.callback_query(F.data == "food_today")
async def food_today_detail(callback: types.CallbackQuery):
    logs = await db.get_food_logs_today()
    if not logs:
        await callback.message.answer("Сегодня ещё ничего не записано. Нажми '➕ Добавить еду'!")
        await callback.answer()
        return

    # Группируем по приёму пищи
    by_meal = {}
    for log in logs:
        m = log['meal_type']
        if m not in by_meal:
            by_meal[m] = []
        by_meal[m].append(log)

    text = f"📋 Питание за {date.today().strftime('%d.%m.%Y')}:\n"
    total_cal = total_p = total_f = total_c = 0

    for meal_code, entries in by_meal.items():
        meal_label = MEAL_EMOJI.get(meal_code, meal_code)
        text += f"\n{meal_label}:\n"
        for e in entries:
            text += f"  • {e['food_name']} {e['grams']:.0f}г — {e['calories']:.0f} ккал (Б:{e['protein']:.1f} Ж:{e['fat']:.1f} У:{e['carbs']:.1f})\n"
            total_cal += e['calories']
            total_p += e['protein']
            total_f += e['fat']
            total_c += e['carbs']

    text += f"\nИТОГО: {total_cal:.0f} ккал | Б:{total_p:.1f}г | Ж:{total_f:.1f}г | У:{total_c:.1f}г"
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "food_add")
async def food_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Выбери приём пищи:", reply_markup=meal_type_keyboard())
    await state.set_state(AddFood.choosing_meal)
    await callback.answer()


@dp.callback_query(F.data.startswith("meal_"), AddFood.choosing_meal)
async def food_choose_meal(callback: types.CallbackQuery, state: FSMContext):
    meal_code = callback.data[5:]
    await state.update_data(meal_type=meal_code)
    await callback.message.answer(
        "Что съела? Напиши название продукта.\n\n"
        "Примеры: куриная грудка, гречка, яблоко, лосось, брокколи\n\n"
        "Напиши /foodlist чтобы увидеть все доступные продукты"
    )
    await state.set_state(AddFood.entering_food)
    await callback.answer()


@dp.message(Command("foodlist"))
async def cmd_foodlist(message: types.Message):
    text = "📋 Доступные продукты (КБЖУ на 100г):\n" + get_food_list()
    await message.answer(text)


@dp.message(AddFood.entering_food)
async def food_enter_name(message: types.Message, state: FSMContext):
    query = message.text.strip().lower()
    name, values = find_food(query)

    if not name:
        await message.answer(
            f"Продукт '{message.text}' не найден.\n\n"
            f"Попробуй: курица, гречка, яблоко, лосось...\n"
            f"Или /foodlist для полного списка"
        )
        return

    cal, p, f, c = values
    await state.update_data(food_name=name, per100=(cal, p, f, c))
    await message.answer(
        f"✅ {name.capitalize()} — на 100г: {cal} ккал | Б:{p}г | Ж:{f}г | У:{c}г\n\n"
        f"Сколько грамм?"
    )
    await state.set_state(AddFood.entering_grams)


@dp.message(AddFood.entering_grams)
async def food_enter_grams(message: types.Message, state: FSMContext):
    try:
        grams = float(message.text.replace(",", "."))
        if grams <= 0 or grams > 2000:
            await message.answer("Введи адекватное количество граммов (1–2000)")
            return

        data = await state.get_data()
        cal100, p100, f100, c100 = data['per100']
        factor = grams / 100

        calories = round(cal100 * factor, 1)
        protein  = round(p100  * factor, 1)
        fat      = round(f100  * factor, 1)
        carbs    = round(c100  * factor, 1)

        await db.init_food_db()
        await db.save_food_log(
            meal_type=data['meal_type'],
            food_name=data['food_name'],
            calories=calories,
            protein=protein,
            fat=fat,
            carbs=carbs,
            grams=grams,
            log_date=date.today()
        )

        meal_label = MEAL_EMOJI.get(data['meal_type'], data['meal_type'])
        totals = await db.get_food_totals_today()

        text = (
            f"✅ Записано!\n\n"
            f"{meal_label}: {data['food_name'].capitalize()} {grams:.0f}г\n"
            f"{calories:.0f} ккал | Б:{protein:.1f}г | Ж:{fat:.1f}г | У:{carbs:.1f}г\n\n"
            f"За сегодня итого:\n"
            f"Калории: {totals['calories']:.0f} / 1500 ккал\n"
            f"Белки: {totals['protein']:.1f} / 115 г\n"
            f"Жиры: {totals['fat']:.1f} / 50 г\n"
            f"Углеводы: {totals['carbs']:.1f} / 140 г"
        )
        await message.answer(text, reply_markup=food_menu_keyboard())
        await state.clear()

    except ValueError:
        await message.answer("Введи число, например: 150 или 200")


@dp.callback_query(F.data == "food_list")
async def food_list_cb(callback: types.CallbackQuery):
    text = "📋 Доступные продукты (КБЖУ на 100г):\n" + get_food_list()
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(F.data == "food_delete_last")
async def food_delete_last(callback: types.CallbackQuery):
    await db.init_food_db()
    deleted = await db.delete_last_food_log()
    if deleted:
        totals = await db.get_food_totals_today()
        await callback.message.answer(
            f"🗑 Последняя запись удалена.\n\n"
            f"Итого за сегодня: {totals['calories']:.0f} ккал | "
            f"Б:{totals['protein']:.1f}г | Ж:{totals['fat']:.1f}г | У:{totals['carbs']:.1f}г"
        )
    else:
        await callback.message.answer("Нет записей для удаления.")
    await callback.answer()


# ═══════════════════════════════════════════
# ВЕС ТЕЛА
# ═══════════════════════════════════════════

class LogBodyWeight(StatesGroup):
    entering_weight = State()
    entering_note = State()


@dp.message(F.text == "⚖️ Мой вес")
async def body_weight_menu(message: types.Message):
    history = await db.get_body_weight_history(limit=7)

    text = "⚖️ Мой вес\n\n"

    if history:
        # Последний вес
        last = history[0]
        text += f"Последний: {last['weight']} кг ({last['log_date']})\n"

        # Динамика
        if len(history) >= 2:
            diff = round(last['weight'] - history[-1]['weight'], 1)
            arrow = "📉" if diff < 0 else "📈" if diff > 0 else "➡️"
            text += f"{arrow} За {len(history)} замеров: {'+' if diff > 0 else ''}{diff} кг\n"

        text += "\nИстория:\n"
        for entry in history:
            note = f" — {entry['note']}" if entry['note'] else ""
            text += f"📅 {entry['log_date']}: {entry['weight']} кг{note}\n"
    else:
        text += "Пока нет записей. Начни отслеживать свой вес!\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Записать вес", callback_data="bw_add")],
        [InlineKeyboardButton(text="📊 Вся история", callback_data="bw_history")],
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "bw_add")
async def bw_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи свой вес в кг (например: 53.2):")
    await state.set_state(LogBodyWeight.entering_weight)
    await callback.answer()


@dp.message(LogBodyWeight.entering_weight)
async def bw_enter_weight(message: types.Message, state: FSMContext):
    try:
        weight = float(message.text.replace(",", "."))
        if weight < 30 or weight > 200:
            await message.answer("Введи адекватный вес (30–200 кг)")
            return
        await state.update_data(weight=weight)
        await message.answer(
            f"Вес {weight} кг записан!\n\nДобавить заметку? (например: после тренировки, утром)\nИли напиши 'нет' чтобы пропустить."
        )
        await state.set_state(LogBodyWeight.entering_note)
    except ValueError:
        await message.answer("Введи число, например: 53.2")


@dp.message(LogBodyWeight.entering_note)
async def bw_enter_note(message: types.Message, state: FSMContext):
    note = "" if message.text.lower() in ["нет", "no", "-"] else message.text.strip()
    data = await state.get_data()

    await db.init_bodyweight_db()
    await db.save_body_weight(
        weight=data['weight'],
        log_date=date.today(),
        note=note
    )

    # Проверяем динамику
    history = await db.get_body_weight_history(limit=2)
    text = f"✅ Записано: {data['weight']} кг\n📅 {date.today().strftime('%d.%m.%Y')}"
    if len(history) >= 2:
        diff = round(history[0]['weight'] - history[1]['weight'], 1)
        arrow = "📉" if diff < 0 else "📈" if diff > 0 else "➡️"
        text += f"\n\n{arrow} Изменение: {'+' if diff > 0 else ''}{diff} кг с прошлого замера"

    await message.answer(text, reply_markup=main_keyboard())
    await state.clear()


@dp.callback_query(F.data == "bw_history")
async def bw_history(callback: types.CallbackQuery):
    history = await db.get_body_weight_history(limit=30)
    if not history:
        await callback.message.answer("Нет записей.")
        await callback.answer()
        return

    text = "📊 Вся история веса:\n\n"
    for entry in history:
        note = f" — {entry['note']}" if entry['note'] else ""
        text += f"📅 {entry['log_date']}: {entry['weight']} кг{note}\n"

    # Мин/макс
    weights = [e['weight'] for e in history]
    text += f"\nМинимум: {min(weights)} кг\nМаксимум: {max(weights)} кг"
    if len(weights) >= 2:
        diff = round(history[0]['weight'] - history[-1]['weight'], 1)
        text += f"\nОбщее изменение: {'+' if diff > 0 else ''}{diff} кг"

    await callback.message.answer(text)
    await callback.answer()


# ═══════════════════════════════════════════
# ИСТОРИЯ ПО УПРАЖНЕНИЯМ
# ═══════════════════════════════════════════

@dp.message(F.text == "📈 Прогресс упражнений")
async def exercise_progress_menu(message: types.Message):
    exercises = await db.get_all_exercises_with_logs()

    if not exercises:
        await message.answer(
            "Пока нет записей с весами.\n"
            "Нажми '📝 Записать вес' под упражнением во время тренировки!"
        )
        return

    buttons = []
    for ex in exercises[:15]:
        buttons.append([InlineKeyboardButton(
            text=ex[:40],
            callback_data=f"exprog_{ex[:30]}"
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери упражнение чтобы увидеть прогресс:", reply_markup=kb)


@dp.callback_query(F.data.startswith("exprog_"))
async def show_exercise_progress(callback: types.CallbackQuery):
    ex_name = callback.data[7:]
    history = await db.get_exercise_history(ex_name, limit=10)

    if not history:
        await callback.message.answer("Нет записей по этому упражнению.")
        await callback.answer()
        return

    text = f"📈 {ex_name}\n\n"

    weights = [h['weight'] for h in history if h['weight'] > 0]
    if weights:
        text += f"Лучший вес: {max(weights)} кг\n"
        text += f"Последний: {history[0]['weight']} кг\n\n"

    text += "История:\n"
    for h in history:
        text += f"📅 {h['workout_date']}: {h['weight']} кг x {h['reps']} повт x {h['sets']} подх\n"

    # Прогресс
    if len(weights) >= 2:
        diff = round(max(weights) - min(weights), 1)
        text += f"\nПрогресс: +{diff} кг от минимума до максимума 💪"

    await callback.message.answer(text)
    await callback.answer()

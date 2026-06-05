"""
Telegram бот для тренировок Ирины
Запуск: python bot.py
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
from food_data import FOODS, MEAL_TYPES, MEAL_EMOJI, find_food, calc_kbzhu, get_food_list

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ═══════════════════════════════════════════
# FSM
# ═══════════════════════════════════════════

class LogExercise(StatesGroup):
    entering_weight = State()
    entering_reps = State()
    entering_sets = State()

class SetCycleDay(StatesGroup):
    entering_day = State()

class AddFood(StatesGroup):
    choosing_meal = State()
    entering_food = State()
    entering_grams = State()

class LogBodyWeight(StatesGroup):
    entering_weight = State()
    entering_note = State()


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

def exercise_keyboard(ex_name, ex_index, day):
    safe_name = ex_name[:25]
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выполнил(а)", callback_data=f"done_{day}_{ex_index}_{safe_name}"),
        InlineKeyboardButton(text="📝 Записать вес", callback_data=f"log_{day}_{ex_index}_{safe_name}"),
    ]])

def nutrition_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 КБЖУ на день", callback_data="nutrition_kbzhu")],
        [InlineKeyboardButton(text="✅ Можно есть", callback_data="nutrition_ok")],
        [InlineKeyboardButton(text="❌ Лучше избегать", callback_data="nutrition_avoid")],
        [InlineKeyboardButton(text="🍽️ Примеры приёмов пищи", callback_data="nutrition_meals")],
    ])

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
        "• Дневник питания с КБЖУ\n"
        "• Отслеживать вес тела\n"
        "• Учитывать фазу цикла и менять блоки каждые 2 недели\n\n"
        "Выбирай что нужно 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())


# ═══════════════════════════════════════════
# Тренировка
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
    day = callback.data.split("_")[1]
    workouts = get_current_workouts()
    workout = workouts[day]
    block_info = get_block_info()
    header = (
        f"🏋️ {workout['name']}\n({block_info['name']})\n\n"
        f"🔥 Разминка: эллипс/дорожка 10 мин\n"
        f"Повороты головы, вращение плеч, наклоны корпуса, приседания без веса — по 15 повт\n\n"
        f"Поехали! Отмечай каждое упражнение 👇"
    )
    await callback.message.answer(header)
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
        await callback.message.answer(text, reply_markup=exercise_keyboard(ex['name'], i, day))
    await callback.message.answer("Удачной тренировки! 💪", reply_markup=main_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    parts = callback.data.split("_", 3)
    ex_name = parts[3] if len(parts) > 3 else "упражнение"
    await db.save_workout_log(exercise=ex_name, weight=0, reps=0, sets=0,
                               workout_date=date.today(), done_only=True)
    new_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнено!", callback_data="noop")]])
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except Exception:
        pass
    await callback.answer("✅ Отмечено!")


@dp.callback_query(F.data.startswith("log_"))
async def log_from_workout(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 3)
    ex_name = parts[3] if len(parts) > 3 else "упражнение"
    await state.update_data(exercise=ex_name, day=parts[1], ex_index=parts[2])
    await callback.message.answer(f"📝 {ex_name}\n\nСколько кг? (если без веса — напиши 0)")
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
        await db.save_workout_log(exercise=data['exercise'], weight=data['weight'],
                                   reps=data['reps'], sets=sets, workout_date=date.today())
        weight_str = f"{data['weight']} кг x " if data['weight'] > 0 else ""
        await message.answer(
            f"✅ Записано!\n\n💪 {data['exercise']}\n"
            f"📊 {weight_str}{data['reps']} повт x {sets} подходов\n"
            f"📅 {date.today().strftime('%d.%m.%Y')}",
            reply_markup=main_keyboard()
        )
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
        f"🌸 Менструальный цикл\n\nДень цикла: {cycle_day} из 28\nФаза: {phase}\n\n"
        f"💡 {note}\n\n"
        f"Режим по фазам:\n"
        f"🔴 Менструация (1-7): -20-30% веса, можно пропустить\n"
        f"🟢 Фолликулярная (8-13): Максимум нагрузки!\n"
        f"🟡 Овуляция (14-16): Пик силы, следи за техникой\n"
        f"🟠 Лютеиновая (17-28): Постепенно снижай к концу\n\n"
        f"Обновить день цикла: /setcycle"
    )
    await message.answer(text)


@dp.message(Command("setcycle"))
async def set_cycle(message: types.Message, state: FSMContext):
    await message.answer("Введи текущий день цикла (1-28):")
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
# Питание — справочник
# ═══════════════════════════════════════════

@dp.message(F.text == "🥗 Питание")
async def nutrition_menu(message: types.Message):
    await message.answer("Питание и продукты 🥗", reply_markup=nutrition_keyboard())


@dp.callback_query(F.data == "nutrition_kbzhu")
async def show_kbzhu(callback: types.CallbackQuery):
    await callback.message.answer(
        "📊 Дневная норма КБЖУ\n\nПараметры: 164 см, 53 кг\nЦель: минус 5 кг, просушка ног\n\n"
        "Норма (дефицит):\nКалории: ~1450-1550 ккал\nБелок: 110-120 г\nЖиры: 45-55 г\nУглеводы: 130-150 г\n\n"
        "В тренировочный день:\nКалории: ~1600-1700 ккал\nБелок: 120-130 г\nЖиры: 50-60 г\nУглеводы: 160-180 г"
    )
    await callback.answer()


@dp.callback_query(F.data == "nutrition_ok")
async def show_ok_foods(callback: types.CallbackQuery):
    await callback.message.answer(
        "✅ Можно свободно:\n\nБелок: курица, индейка, кролик, говядина, треска, тунец, лосось, форель, креветки\n"
        "Злаки: гречка, рис, рожь, овёс, перловка\n"
        "Овощи: картофель, помидор, огурец, морковь, свёкла, шпинат, брокколи, авокадо\n"
        "Фрукты: яблоко, персик, черника, клубника, груша, слива\n"
        "Молочное: яйцо перепелиное, сыр швейцарский, молоко козье"
    )
    await callback.answer()


@dp.callback_query(F.data == "nutrition_avoid")
async def show_avoid_foods(callback: types.CallbackQuery):
    await callback.message.answer(
        "❌ Лучше избегать:\n\nАрахис (349), дрожжи пивные (466), пекарские (311)\n"
        "Масло сливочное (244), брынза овечья (314), йогурт (315)\n"
        "Коровье молоко (167), сыворотка (150), кальмар (206), кукуруза (165)\n"
        "Перец чёрный (298), чили (267), мёд (217), горчица (217)"
    )
    await callback.answer()


@dp.callback_query(F.data == "nutrition_meals")
async def show_meals(callback: types.CallbackQuery):
    await callback.message.answer(
        "Примеры приёмов пищи\n\n"
        "Завтрак: овсянка 150г + яблоко + 3 перепелиных яйца — ~350 ккал\n"
        "Перекус: форель 100г + огурец — ~200 ккал\n"
        "Обед: куриная грудка 150г + гречка 100г + брокколи — ~450 ккал\n"
        "До трени: рис 80г + индейка 120г — ~400 ккал\n"
        "После трени: лосось 150г + картофель 150г + шпинат — ~400 ккал\n"
        "Ужин: говядина 130г + овощи тушёные — ~300 ккал"
    )
    await callback.answer()


# ═══════════════════════════════════════════
# Дневник питания
# ═══════════════════════════════════════════

@dp.message(F.text == "🍽 Дневник питания")
async def food_diary(message: types.Message):
    totals = await db.get_food_totals_today()
    bar_cal = min(int(totals['calories'] / 1500 * 10), 10)
    bar_p = min(int(totals['protein'] / 115 * 10), 10)
    text = (
        f"🍽 Дневник питания — {date.today().strftime('%d.%m.%Y')}\n\n"
        f"Калории:  {totals['calories']:.0f} / 1500 ккал  {'█'*bar_cal}{'░'*(10-bar_cal)}\n"
        f"Белки:    {totals['protein']:.1f} / 115 г  {'█'*bar_p}{'░'*(10-bar_p)}\n"
        f"Жиры:     {totals['fat']:.1f} / 50 г\n"
        f"Углеводы: {totals['carbs']:.1f} / 140 г\n\n"
        f"Записей за день: {totals['entries']}"
    )
    await message.answer(text, reply_markup=food_menu_keyboard())


@dp.callback_query(F.data == "food_today")
async def food_today_detail(callback: types.CallbackQuery):
    logs = await db.get_food_logs_today()
    if not logs:
        await callback.message.answer("Сегодня ещё ничего не записано!")
        await callback.answer()
        return
    by_meal = {}
    for log in logs:
        m = log['meal_type']
        if m not in by_meal:
            by_meal[m] = []
        by_meal[m].append(log)
    text = f"📋 Питание за {date.today().strftime('%d.%m.%Y')}:\n"
    total_cal = total_p = total_f = total_c = 0
    for meal_code, entries in by_meal.items():
        text += f"\n{MEAL_EMOJI.get(meal_code, meal_code)}:\n"
        for e in entries:
            text += f"  • {e['food_name']} {e['grams']:.0f}г — {e['calories']:.0f} ккал (Б:{e['protein']:.1f} Ж:{e['fat']:.1f} У:{e['carbs']:.1f})\n"
            total_cal += e['calories']; total_p += e['protein']; total_f += e['fat']; total_c += e['carbs']
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
    await state.update_data(meal_type=callback.data[5:])
    await callback.message.answer(
        "Что съела? Напиши название продукта.\nПримеры: куриная грудка, гречка, яблоко\n\n/foodlist — список всех продуктов"
    )
    await state.set_state(AddFood.entering_food)
    await callback.answer()


@dp.message(Command("foodlist"))
async def cmd_foodlist(message: types.Message):
    await message.answer("📋 Доступные продукты (КБЖУ на 100г):\n" + get_food_list())


@dp.message(AddFood.entering_food)
async def food_enter_name(message: types.Message, state: FSMContext):
    name, values = find_food(message.text.strip().lower())
    if not name:
        await message.answer(f"Продукт '{message.text}' не найден. Попробуй: курица, гречка, яблоко\n/foodlist — полный список")
        return
    cal, p, f, c = values
    await state.update_data(food_name=name, per100=(cal, p, f, c))
    await message.answer(f"✅ {name.capitalize()} — на 100г: {cal} ккал | Б:{p}г | Ж:{f}г | У:{c}г\n\nСколько грамм?")
    await state.set_state(AddFood.entering_grams)


@dp.message(AddFood.entering_grams)
async def food_enter_grams(message: types.Message, state: FSMContext):
    try:
        grams = float(message.text.replace(",", "."))
        if grams <= 0 or grams > 2000:
            await message.answer("Введи от 1 до 2000 граммов")
            return
        data = await state.get_data()
        cal100, p100, f100, c100 = data['per100']
        f = grams / 100
        calories = round(cal100*f, 1); protein = round(p100*f, 1)
        fat = round(f100*f, 1); carbs = round(c100*f, 1)
        await db.save_food_log(meal_type=data['meal_type'], food_name=data['food_name'],
                                calories=calories, protein=protein, fat=fat, carbs=carbs,
                                grams=grams, log_date=date.today())
        totals = await db.get_food_totals_today()
        await message.answer(
            f"✅ Записано!\n{MEAL_EMOJI.get(data['meal_type'], '')}: {data['food_name'].capitalize()} {grams:.0f}г\n"
            f"{calories:.0f} ккал | Б:{protein:.1f}г | Ж:{fat:.1f}г | У:{carbs:.1f}г\n\n"
            f"За сегодня: {totals['calories']:.0f} ккал | Б:{totals['protein']:.1f}г | У:{totals['carbs']:.1f}г",
            reply_markup=food_menu_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("Введи число, например: 150")


@dp.callback_query(F.data == "food_list")
async def food_list_cb(callback: types.CallbackQuery):
    await callback.message.answer("📋 Доступные продукты:\n" + get_food_list())
    await callback.answer()


@dp.callback_query(F.data == "food_delete_last")
async def food_delete_last(callback: types.CallbackQuery):
    deleted = await db.delete_last_food_log()
    if deleted:
        totals = await db.get_food_totals_today()
        await callback.message.answer(f"🗑 Удалено.\nИтого: {totals['calories']:.0f} ккал | Б:{totals['protein']:.1f}г")
    else:
        await callback.message.answer("Нет записей для удаления.")
    await callback.answer()


# ═══════════════════════════════════════════
# Вес тела
# ═══════════════════════════════════════════

@dp.message(F.text == "⚖️ Мой вес")
async def body_weight_menu(message: types.Message):
    history = await db.get_body_weight_history(limit=7)
    text = "⚖️ Мой вес\n\n"
    if history:
        last = history[0]
        text += f"Последний: {last['weight']} кг ({last['log_date']})\n"
        if len(history) >= 2:
            diff = round(last['weight'] - history[-1]['weight'], 1)
            arrow = "📉" if diff < 0 else "📈" if diff > 0 else "➡️"
            text += f"{arrow} За {len(history)} замеров: {'+' if diff > 0 else ''}{diff} кг\n"
        text += "\nИстория:\n"
        for e in history:
            note = f" — {e['note']}" if e['note'] else ""
            text += f"📅 {e['log_date']}: {e['weight']} кг{note}\n"
    else:
        text += "Пока нет записей.\n"
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
            await message.answer("Введи вес от 30 до 200 кг")
            return
        await state.update_data(weight=weight)
        await message.answer(f"Вес {weight} кг!\n\nДобавить заметку? (утром, после трени...)\nИли напиши 'нет'")
        await state.set_state(LogBodyWeight.entering_note)
    except ValueError:
        await message.answer("Введи число, например: 53.2")


@dp.message(LogBodyWeight.entering_note)
async def bw_enter_note(message: types.Message, state: FSMContext):
    note = "" if message.text.lower() in ["нет", "no", "-"] else message.text.strip()
    data = await state.get_data()
    await db.save_body_weight(weight=data['weight'], log_date=date.today(), note=note)
    history = await db.get_body_weight_history(limit=2)
    text = f"✅ Записано: {data['weight']} кг\n📅 {date.today().strftime('%d.%m.%Y')}"
    if len(history) >= 2:
        diff = round(history[0]['weight'] - history[1]['weight'], 1)
        arrow = "📉" if diff < 0 else "📈" if diff > 0 else "➡️"
        text += f"\n\n{arrow} Изменение: {'+' if diff > 0 else ''}{diff} кг"
    await message.answer(text, reply_markup=main_keyboard())
    await state.clear()


@dp.callback_query(F.data == "bw_history")
async def bw_full_history(callback: types.CallbackQuery):
    history = await db.get_body_weight_history(limit=30)
    if not history:
        await callback.message.answer("Нет записей.")
        await callback.answer()
        return
    text = "📊 История веса:\n\n"
    for e in history:
        note = f" — {e['note']}" if e['note'] else ""
        text += f"📅 {e['log_date']}: {e['weight']} кг{note}\n"
    weights = [e['weight'] for e in history]
    text += f"\nМин: {min(weights)} кг | Макс: {max(weights)} кг"
    if len(weights) >= 2:
        diff = round(history[0]['weight'] - history[-1]['weight'], 1)
        text += f"\nОбщее: {'+' if diff > 0 else ''}{diff} кг"
    await callback.message.answer(text)
    await callback.answer()


# ═══════════════════════════════════════════
# Прогресс упражнений
# ═══════════════════════════════════════════

@dp.message(F.text == "📈 Прогресс упражнений")
async def exercise_progress_menu(message: types.Message):
    exercises = await db.get_all_exercises_with_logs()
    if not exercises:
        await message.answer("Пока нет записей с весами.\nНажми '📝 Записать вес' во время тренировки!")
        return
    buttons = [[InlineKeyboardButton(text=ex[:40], callback_data=f"exprog_{ex[:30]}")] for ex in exercises[:15]]
    await message.answer("Выбери упражнение:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


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
        text += f"Лучший вес: {max(weights)} кг\nПоследний: {history[0]['weight']} кг\n\n"
    text += "История:\n"
    for h in history:
        text += f"📅 {h['workout_date']}: {h['weight']} кг x {h['reps']} повт x {h['sets']} подх\n"
    if len(weights) >= 2:
        diff = round(max(weights) - min(weights), 1)
        text += f"\nПрогресс: +{diff} кг 💪"
    await callback.message.answer(text)
    await callback.answer()


# ═══════════════════════════════════════════
# История и прогресс
# ═══════════════════════════════════════════

@dp.message(F.text == "📋 История тренировок")
async def show_history(message: types.Message):
    logs = await db.get_workout_history()
    if not logs:
        await message.answer("Пока нет записей. Начни тренировку!")
        return
    by_date = {}
    for log in logs:
        d = log['date']
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(log)
    text = "📋 История тренировок:\n\n"
    for d in list(by_date.keys())[:5]:
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
    text = f"📊 Твой прогресс\n\n🏋️ Всего записей: {stats['total_logs']}\n📅 Первая запись: {stats['first_date'] or 'нет данных'}\n\n"
    if stats['best_weights']:
        text += "🏆 Лучшие веса:\n"
        for ex, weight in list(stats['best_weights'].items())[:8]:
            if weight > 0:
                text += f"• {ex}: {weight} кг\n"
    await message.answer(text)


# ═══════════════════════════════════════════
# Запуск — webhook для Render
# ═══════════════════════════════════════════

async def on_startup(app):
    await db.init_db()
    await db.init_food_db()
    await db.init_bodyweight_db()
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if webhook_url:
        await bot.set_webhook(f"{webhook_url}/webhook")
        logger.info(f"Webhook: {webhook_url}/webhook")
    logger.info("Бот запущен!")


async def on_shutdown(app):
    await bot.delete_webhook()


def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    PORT = int(os.getenv("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

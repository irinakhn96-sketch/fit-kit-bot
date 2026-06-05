"""
Поиск продуктов через Open Food Facts API
Бесплатная база — миллионы продуктов
"""

import aiohttp
from food_data import FOODS, find_food


async def search_product(query: str) -> list[dict]:
    """
    Ищет продукт сначала в локальной базе, потом в Open Food Facts.
    Возвращает список найденных продуктов с КБЖУ.
    """
    # Сначала ищем в локальной базе
    name, values = find_food(query)
    results = []
    if name:
        cal, p, f, c = values
        results.append({
            "name": name,
            "calories": cal,
            "protein": p,
            "fat": f,
            "carbs": c,
            "source": "local",
        })

    # Потом ищем в Open Food Facts
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://world.openfoodfacts.org/cgi/search.pl"
            params = {
                "search_terms": query,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": 5,
                "fields": "product_name,nutriments,brands",
                "lc": "ru",
            }
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    products = data.get("products", [])
                    for p in products:
                        name_raw = p.get("product_name", "").strip()
                        if not name_raw:
                            continue
                        n = p.get("nutriments", {})
                        cal = n.get("energy-kcal_100g") or n.get("energy_100g", 0)
                        # Конвертируем из кДж если нужно
                        if cal and cal > 900:
                            cal = round(cal / 4.184, 1)
                        protein = n.get("proteins_100g", 0) or 0
                        fat = n.get("fat_100g", 0) or 0
                        carbs = n.get("carbohydrates_100g", 0) or 0
                        if cal and cal > 0:
                            brand = p.get("brands", "").split(",")[0].strip()
                            display_name = f"{name_raw}" + (f" ({brand})" if brand else "")
                            results.append({
                                "name": display_name[:50],
                                "calories": round(float(cal), 1),
                                "protein": round(float(protein), 1),
                                "fat": round(float(fat), 1),
                                "carbs": round(float(carbs), 1),
                                "source": "off",
                            })
    except Exception as e:
        pass  # Если API недоступен — используем только локальную базу

    return results[:6]  # Максимум 6 результатов


def format_product_choice(products: list[dict]) -> tuple[str, list]:
    """Формирует текст и кнопки для выбора продукта"""
    if not products:
        return "Ничего не найдено", []

    text = "Выбери продукт:\n\n"
    buttons = []
    for i, p in enumerate(products):
        source_icon = "📦" if p["source"] == "off" else "✅"
        text += f"{i+1}. {source_icon} {p['name']}\n"
        text += f"   {p['calories']} ккал | Б:{p['protein']}г | Ж:{p['fat']}г | У:{p['carbs']}г\n\n"
        # Кодируем данные в callback
        cb = f"pick_{i}_{p['calories']}_{p['protein']}_{p['fat']}_{p['carbs']}_{p['name'][:20]}"
        buttons.append([{"text": f"{i+1}. {p['name'][:35]}", "cb": cb}])

    return text, buttons

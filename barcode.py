"""
Распознавание штрихкода с фото через ZXing API
и поиск продукта в Open Food Facts
"""

import aiohttp


async def decode_barcode_from_url(image_url: str) -> str | None:
    """Распознаёт штрихкод с фото через ZXing"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://zxing.org/w/decode?u={image_url}&maxW=400&maxH=400&fmt=json"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get("type") and data.get("rawText"):
                        return data["rawText"].strip()
    except Exception:
        pass
    return None


async def get_product_by_barcode(barcode: str) -> dict | None:
    """Ищет продукт по штрихкоду в Open Food Facts"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == 1:
                        p = data["product"]
                        name = p.get("product_name_ru") or p.get("product_name") or p.get("generic_name", "")
                        brand = p.get("brands", "").split(",")[0].strip()
                        n = p.get("nutriments", {})

                        cal = n.get("energy-kcal_100g") or n.get("energy-kcal") or 0
                        if not cal:
                            kj = n.get("energy_100g") or n.get("energy") or 0
                            cal = round(kj / 4.184, 1) if kj else 0

                        protein = n.get("proteins_100g") or n.get("proteins") or 0
                        fat = n.get("fat_100g") or n.get("fat") or 0
                        carbs = n.get("carbohydrates_100g") or n.get("carbohydrates") or 0

                        if name and cal:
                            display_name = name
                            if brand and brand.lower() not in name.lower():
                                display_name = f"{name} ({brand})"
                            return {
                                "name": display_name[:60],
                                "calories": round(float(cal), 1),
                                "protein": round(float(protein), 1),
                                "fat": round(float(fat), 1),
                                "carbs": round(float(carbs), 1),
                                "barcode": barcode,
                            }
    except Exception:
        pass
    return None

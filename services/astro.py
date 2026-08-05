from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import swisseph as swe
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

PLANETS = {
    "Солнце": swe.SUN, "Луна": swe.MOON, "Меркурий": swe.MERCURY,
    "Венера": swe.VENUS, "Марс": swe.MARS, "Юпитер": swe.JUPITER,
    "Сатурн": swe.SATURN, "Уран": swe.URANUS, "Нептун": swe.NEPTUNE,
    "Плутон": swe.PLUTO,
}
SIGNS = ("Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
         "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы")
ASPECTS = {
    0: ("соединение", 8),
    60: ("секстиль", 5),
    90: ("квадрат", 6),
    120: ("тригон", 6),
    180: ("оппозиция", 8),
}
_TIMEZONE_FINDER = TimezoneFinder()


def parse_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")


def parse_time(value: str | None) -> str:
    if not value or value.lower().strip() in {"нет", "не знаю", "-"}:
        return "12:00"
    return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")


def is_approximate_time(value: str | None) -> bool:
    return not value or value.lower().strip() in {"нет", "не знаю", "-"}


@lru_cache(maxsize=256)
def geocode(place: str) -> tuple[float, float]:
    location = Nominatim(user_agent="astro_bot_mary").geocode(place, language="ru")
    if not location:
        raise ValueError("Не удалось найти этот город. Попробуйте написать город и страну.")
    return float(location.latitude), float(location.longitude)


@lru_cache(maxsize=256)
def timezone_for_coordinates(latitude: float, longitude: float) -> str:
    timezone_name = _TIMEZONE_FINDER.timezone_at(lat=latitude, lng=longitude)
    if not timezone_name:
        raise ValueError("Не удалось определить часовой пояс для места рождения.")
    return timezone_name


def local_time_to_utc(
    date: str, time: str, latitude: float, longitude: float
) -> tuple[datetime, str]:
    local_time = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    timezone_name = timezone_for_coordinates(latitude, longitude)
    localized = local_time.replace(tzinfo=ZoneInfo(timezone_name))
    return localized.astimezone(timezone.utc), timezone_name


def calculate_chart(
    date: str,
    time: str,
    latitude: float,
    longitude: float,
    *,
    time_is_approximate: bool = False,
) -> dict:
    utc_moment, timezone_name = local_time_to_utc(date, time, latitude, longitude)
    jd = swe.julday(
        utc_moment.year,
        utc_moment.month,
        utc_moment.day,
        utc_moment.hour + utc_moment.minute / 60,
    )
    positions = {}
    for name, planet in PLANETS.items():
        result, _ = swe.calc_ut(jd, planet)
        longitude_value = result[0] % 360
        positions[name] = {
            "longitude": round(longitude_value, 2),
            "sign": SIGNS[int(longitude_value // 30)],
            "degree": round(longitude_value % 30, 1),
        }
    houses, _ = swe.houses(jd, latitude, longitude, b"P")
    house_cusps = [round(cusp % 360, 2) for cusp in houses]
    for position in positions.values():
        position["house"] = _house_for_longitude(position["longitude"], house_cusps)
    ascendant = houses[0] % 360
    return {
        "date": date,
        "time": time,
        "utc_time": utc_moment.strftime("%Y-%m-%d %H:%M UTC"),
        "timezone": timezone_name,
        "time_is_approximate": time_is_approximate,
        "latitude": latitude,
        "longitude": longitude,
        "planets": positions,
        "ascendant": {"longitude": round(ascendant, 2), "sign": SIGNS[int(ascendant // 30)]},
        "houses": house_cusps,
        "aspects": _calculate_aspects(positions),
    }


def _house_for_longitude(longitude: float, cusps: list[float]) -> int:
    for index, cusp in enumerate(cusps):
        next_cusp = cusps[(index + 1) % 12]
        if cusp <= next_cusp and cusp <= longitude < next_cusp:
            return index + 1
        if cusp > next_cusp and (longitude >= cusp or longitude < next_cusp):
            return index + 1
    return 12


def _calculate_aspects(planets: dict[str, dict]) -> list[dict]:
    result = []
    planet_items = list(planets.items())
    for index, (first_name, first) in enumerate(planet_items):
        for second_name, second in planet_items[index + 1:]:
            distance = abs(first["longitude"] - second["longitude"])
            distance = min(distance, 360 - distance)
            for angle, (name, orb) in ASPECTS.items():
                difference = abs(distance - angle)
                if difference <= orb:
                    result.append({
                        "first": first_name,
                        "second": second_name,
                        "type": name,
                        "angle": angle,
                        "orb": round(difference, 2),
                    })
                    break
    return result


def calculate_synastry(first_chart: dict, second_chart: dict) -> list[dict]:
    result = []
    for first_name, first in first_chart["planets"].items():
        for second_name, second in second_chart["planets"].items():
            distance = abs(first["longitude"] - second["longitude"])
            distance = min(distance, 360 - distance)
            for angle, (name, orb) in ASPECTS.items():
                difference = abs(distance - angle)
                if difference <= orb:
                    result.append({
                        "first": first_name,
                        "second": second_name,
                        "type": name,
                        "angle": angle,
                        "orb": round(difference, 2),
                    })
                    break
    return result


def teaser(chart: dict, report_type: str, second_chart: dict | None = None) -> str:
    p = chart["planets"]
    sun, moon, venus, jupiter = p["Солнце"], p["Луна"], p["Венера"], p["Юпитер"]
    if report_type == "personality":
        return (
            f"• Ваше Солнце в знаке {sun['sign']} — это основной вектор характера и силы.\n"
            f"• Луна в {moon['sign']} показывает, что эмоционально вам важно чувствовать безопасность.\n"
            f"• Венера в {venus['sign']} раскрывает ваш стиль любви и личные ценности.\n"
            f"• Асцендент — {chart['ascendant']['sign']}: так вы проявляетесь при первом знакомстве."
        )
    if report_type == "money":
        return (
            f"• Юпитер в {jupiter['sign']} подсказывает, через какие качества растёт ваш доход.\n"
            f"• Венера в {venus['sign']} усиливает заработок там, где есть вкус, люди и ценность.\n"
            "• Ваш денежный ключ — дисциплина, понятная цена своего труда и регулярные действия.\n"
            "• Полный отчёт покажет сильные финансовые сценарии и зоны риска."
        )
    other = second_chart["planets"]
    return (
        f"• Солнца в знаках {sun['sign']} и {other['Солнце']['sign']} задают общую динамику пары.\n"
        f"• Ваши Венеры: {venus['sign']} и {other['Венера']['sign']} — важный показатель симпатии.\n"
        f"• Лунная связка {moon['sign']} и {other['Луна']['sign']} говорит о стиле заботы.\n"
        "• Полный отчёт разберёт притяжение, быт, конфликты и точки роста."
    )

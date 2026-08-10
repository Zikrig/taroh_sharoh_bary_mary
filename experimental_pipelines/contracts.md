# Контракты данных

Контракты являются черновыми и предназначены для экспериментов. Их задача —
разделить расчёт карты, смысловой профиль и оформление текста.

## 1. Вход запуска

```json
{
  "schema_version": "experimental.v1",
  "generation_id": "gen_01J...",
  "product": "PERSONALITY_FREE",
  "user": {
    "name": "Анна",
    "birth_date": "1998-07-24",
    "birth_time": "14:35",
    "birth_place": "Москва, Россия",
    "time_is_approximate": false
  },
  "partner": null,
  "options": {
    "language": "ru",
    "channel": "telegram"
  }
}
```

## 2. Карта

```json
{
  "chart_version": "astro.v1",
  "primary_chart": {
    "date": "1998-07-24",
    "time": "14:35",
    "timezone": "Europe/Moscow",
    "time_is_approximate": false,
    "ascendant": {},
    "houses": [],
    "planets": {},
    "aspects": []
  },
  "partner_chart": null,
  "synastry_aspects": []
}
```

## 3. Профиль

Профиль — промежуточный слой, который можно переиспользовать для разных
продуктов. Каждое утверждение должно иметь ссылки на факты.

```json
{
  "profile_version": "profile.v1",
  "product": "PERSONALITY_FREE",
  "themes": [
    {
      "id": "core_identity",
      "summary": "Самостоятельность сочетается с потребностью в эмоциональной опоре.",
      "facts": ["primary.sun.sign", "primary.moon.sign"],
      "confidence": "moderate"
    }
  ],
  "strengths": [
    {
      "title": "Адаптивность",
      "manifestations": ["быстрое переключение", "поиск решения в новой ситуации"],
      "facts": ["primary.mercury.sign"]
    }
  ],
  "challenges": [],
  "contradictions": [],
  "relationships": {
    "needs": [],
    "attraction": [],
    "conflict_patterns": [],
    "facts": []
  },
  "career_and_money": {
    "motivation": [],
    "work_style": [],
    "directions": [],
    "facts": []
  },
  "growth_points": []
}
```

## 4. Текстовый результат

```json
{
  "result_version": "report.v1",
  "generation_id": "gen_01J...",
  "product": "PERSONALITY_FREE",
  "title": "Твой персональный профиль",
  "sections": [
    {
      "id": "portrait",
      "title": "Твой портрет",
      "content": "Текст раздела...",
      "fact_ids": ["primary.sun.sign", "primary.moon.sign"],
      "word_count": 120
    }
  ],
  "continuation": {
    "title": "🔐 Это только верхний слой профиля",
    "topics": ["сценарии отношений", "денежный профиль", "точки роста"]
  },
  "disclaimer": "Материал носит символический и развлекательный характер."
}
```

## 5. Ошибка этапа

```json
{
  "stage": "text_generation",
  "code": "INVALID_FACT_REFERENCE",
  "message": "Section portrait references an unknown fact_id.",
  "retryable": true,
  "generation_id": "gen_01J...",
  "attempt": 1
}
```

## 6. Правила контракта

- Не передавать в текстовый этап всю необработанную карту, если продукту нужна
  только её часть.
- Не разрешать ссылки на факты, отсутствующие в `fact_catalog`.
- Не хранить в payload токены, API-ключи, платёжные идентификаторы и лишние
  персональные данные.
- Версионировать схемы отдельно от версий промптов.
- При изменении обязательных полей создавать новую версию контракта.

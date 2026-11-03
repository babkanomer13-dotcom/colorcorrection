"""A human-readable view of recorded decisions, never inferred from the photo."""

TOOLS = {
    "levels_only": "Уровни RGB",
    "auto_color": "Автоцвет → Уровни RGB",
    "auto_tone": "Автотон → Уровни RGB",
    "auto_contrast": "Автоконтраст → Уровни RGB",
    "auto_color_then_tone": "Автоцвет → Автотон → Уровни RGB",
    "auto_color_then_contrast": "Автоцвет → Автоконтраст → Уровни RGB",
}


def processing_report(record, original=False, manual=False):
    decision = record.get("decision")
    if not isinstance(decision, dict) or decision.get("tool") not in TOOLS:
        title, detail = "Обработка V39", "Для этой обработки параметры не сохранены."
    else:
        title = "V39 · " + TOOLS[decision["tool"]]
        values = decision.get("levels")
        if (
            isinstance(values, (list, tuple))
            and len(values) == 5
            and all(type(value) is int for value in values)
            and 0 <= values[0] < values[1] <= 255
            and 10 <= values[2] <= 999
            and 0 <= values[3] < values[4] <= 255
        ):
            black, white, gamma, out_black, out_white = values
            gamma = f"{gamma / 100:.2f}".replace(".", ",")
            detail = (
                f"Вход: {black}–{white} · Гамма: {gamma} · "
                f"Выход: {out_black}–{out_white} · Весь кадр"
            )
        else:
            detail = "Значения уровней недоступны."
    if original:
        note = (
            "Сейчас: ручные правки исходника. Коррекция V39 отключена."
            if manual
            else "Сейчас: исходник. Коррекция V39 отключена, ручные правки сброшены."
        )
    elif manual:
        note = "Поверх результата V39 применены ручные правки."
    elif record.get("reason") == "no_pixel_changes":
        note = "Выбранные параметры не изменили пиксели этого кадра."
    else:
        note = ""
    return title, detail, note

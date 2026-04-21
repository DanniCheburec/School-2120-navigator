import os
import json
import requests
from typing import Optional, Dict, List

LLAMA_URL   = os.getenv("LLAMA_URL", "http://localhost:11434")
LLAMA_MODEL = os.getenv("LLAMA_MODEL", "llama3")
SCHOOL_INFO_PATH = os.getenv("SCHOOL_INFO_PATH", "school_info.txt")

# ─────────────────────────── Загрузка базы знаний ───────────────────────────

def _load_school_info() -> List[str]:
    try:
        with open(SCHOOL_INFO_PATH, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

_SCHOOL_INFO = _load_school_info()

def search_knowledge(query: str, k: int = 3) -> List[str]:
    q = (query or "").lower()
    results = [line for line in _SCHOOL_INFO if q in line.lower()]
    return results[:k]


# ─────────────────────────── Fuzzy поиск ───────────────────────────

def find_room(query: str, rooms: List[str]) -> Optional[str]:
    if not query:
        return None

    # exact
    if query in rooms:
        return query

    # по номеру
    import re
    nums = re.findall(r'\d{3}', query)
    for num in nums:
        for r in rooms:
            if num in r:
                return r

    # fallback fuzzy (без зависимостей)
    q = query.lower()
    for r in rooms:
        rl = r.lower()
        if q in rl or rl in q:
            return r

    return None


# ─────────────────────────── JSON парсинг ───────────────────────────

def parse_json_safe(text: str) -> Optional[Dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except:
        return None


# ─────────────────────────── Prompt ───────────────────────────

def build_system_prompt(rooms: List[str], user_name: str, user_query: str) -> str:
    rooms_str = "\n".join(f"- {r}" for r in rooms[:100])

    knowledge = "\n".join(search_knowledge(user_query))

    return f"""
Ты — навигационный ассистент школы 2120.

Пользователь: {user_name}

РЕЛЕВАНТНАЯ ИНФОРМАЦИЯ:
{knowledge}

СТРОГИЕ ПРАВИЛА:

1. Всегда отвечай на русском
2. Не выдумывай кабинеты, людей или факты
3. Если не уверен — скажи "Не знаю"

4. ЕСЛИ пользователь хочет маршрут:
ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО JSON, БЕЗ ЛЮБОГО ТЕКСТА:

ФОРМАТ:
{{"action":"navigate","from":null,"to":"<точное имя>"}} 

ИЛИ:
{{"action":"navigate","from":"<точное имя>","to":"<точное имя>"}}

5. Используй ТОЛЬКО значения из списка

СПИСОК КАБИНЕТОВ:
{rooms_str}

6. Если вопрос НЕ про маршрут — ответь кратко (1–4 предложения)
"""


# ─────────────────────────── Основной вызов ───────────────────────────

def ask_llama_stream(messages: List[Dict], known_rooms: List[str], user_name: str):
    user_query = messages[-1]["content"] if messages else ""

    system_prompt = build_system_prompt(known_rooms, user_name, user_query)

    payload = {
        "model": LLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt}
        ] + messages,
        "stream": True,
        "options": {
            "temperature": 0.2
        },
    }

    full_text = ""

    try:
        with requests.post(
            f"{LLAMA_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=600,
        ) as resp:

            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue

                try:
                    chunk = json.loads(line)
                except:
                    continue

                token = chunk.get("message", {}).get("content", "")
                full_text += token
                yield token

                if chunk.get("done"):
                    break

    except requests.exceptions.ConnectionError:
        msg = "⚠️ Ollama не запущена"
        yield msg
        return {"text": msg, "action": None}

    except requests.exceptions.Timeout:
        msg = "⚠️ Таймаут модели"
        yield msg
        return {"text": msg, "action": None}

    except Exception as e:
        msg = f"⚠️ Ошибка: {e}"
        yield msg
        return {"text": msg, "action": None}

    # ─────────────────────────── Постобработка ───────────────────────────

    raw = full_text.strip()

    cmd = parse_json_safe(raw)

    if cmd and cmd.get("action") == "navigate":
        resolved_to   = find_room(cmd.get("to"),   known_rooms)
        resolved_from = find_room(cmd.get("from"), known_rooms)

        if resolved_to:
            return {
                "text": "Строю маршрут...",
                "action": {
                    "from": resolved_from,
                    "to": resolved_to
                }
            }
        else:
            return {
                "text": f"Не нашёл кабинет: {cmd.get('to')}",
                "action": None
            }

    # обычный ответ
    yield "__END__" + json.dumps({
    "text": raw,
    "action": None
    })

"""
llm_chat.py  —  чат-бот школы 2120 на базе Ollama (Llama 3).

Локально:  LLAMA_URL=http://localhost:11434
Через ngrok: LLAMA_URL=https://xxxx.ngrok-free.app
"""

# import os
# import re
# import json
# import requests

# LLAMA_URL      = os.getenv("LLAMA_URL", "http://localhost:11434")
# LLAMA_MODEL    = os.getenv("LLAMA_MODEL", "llama3.1:8b-instruct-q4_0")
# SCHOOL_INFO_PATH = os.getenv("SCHOOL_INFO_PATH", "school_info.txt")


# def _load_school_info() -> str:
#     """Читает school_info.txt один раз. Если файла нет — возвращает пустую строку."""
#     try:
#         with open(SCHOOL_INFO_PATH, encoding="utf-8") as f:
#             return f.read().strip()
#     except FileNotFoundError:
#         return ""


# # Загружаем при старте модуля — файл читается один раз, не при каждом запросе
# _SCHOOL_INFO = _load_school_info()


# def build_system_prompt(known_rooms: list[str], user_name: str) -> str:
#     rooms_str = "\n".join(f"- {r}" for r in known_rooms[:80])

#     knowledge_block = ""
#     if _SCHOOL_INFO:
#         knowledge_block = f"""
# БАЗА ЗНАНИЙ О ШКОЛЕ (используй при ответах на вопросы):
# {_SCHOOL_INFO}
# """

#     return f"""Ты — навигационный ассистент школы 2120 (Москва, здание Ш6).
# {knowledge_block}. Имя пользователя: {user_name}
# СТРОГИЕ ПРАВИЛА — нарушать их ЗАПРЕЩЕНО:
# 1. ВСЕГДА отвечай ТОЛЬКО на русском языке. Никакого английского.
# 2. Отвечай КОРОТКО — максимум 2-3 предложения.
# 3. НЕ давай пошаговых инструкций по коридорам — ты не знаешь реальную планировку.
# 4. Если пользователь хочет найти кабинет или построить маршрут — твой ответ должен быть ТОЛЬКО следующий JSON и ничего больше:
# {{"action": "navigate", "from": "<точное название из списка или null>", "to": "<точное название из списка>"}}
# 5. Для поля "to" и "from" используй ТОЛЬКО точные названия из списка ниже. Если похожего нет — используй null.
# 6. Если вопрос не про навигацию — отвечай обычным текстом без JSON.

# ДОСТУПНЫЕ ТОЧКИ НАВИГАЦИИ:
# {rooms_str}
# """


# def _extract_json(text: str) -> dict | None:
#     """Ищет JSON-объект в любом месте строки."""
#     match = re.search(r'\{{[^{{}}]+\}}', text, re.DOTALL)
#     if not match:
#         return None
#     try:
#         return json.loads(match.group())
#     except json.JSONDecodeError:
#         return None


# def _find_best_room(query: str, known_rooms: list[str]) -> str | None:
#     """Нечёткий поиск кабинета по названию или номеру."""
#     if not query:
#         return None
#     if query in known_rooms:
#         return query
#     numbers = re.findall(r'\d{3}', query)
#     for num in numbers:
#         for room in known_rooms:
#             if num in room:
#                 return room
#     q = query.lower()
#     for room in known_rooms:
#         if q in room.lower() or room.lower() in q:
#             return room
#     return None


# def ask_llama_stream(messages: list[dict], known_rooms: list[str], user_name: str):
#     """
#     Генератор: отдаёт токены по мере получения от Ollama (stream=True).
#     После завершения стрима возвращает финальный dict через StopIteration.value:

#         result = yield from ask_llama_stream(...)

#     Итоговый dict:
#       {
#         "text": "полный текст ответа",
#         "action": None | {"from": str|None, "to": str}
#       }
#     """
#     payload = {
#         "model": LLAMA_MODEL,
#         "messages": [
#             {"role": "system", "content": build_system_prompt(known_rooms, user_name)}
#         ] + messages,
#         "stream": True,
#         "options": {"temperature": 0.3},
#     }

#     headers = {
#     "ngrok-skip-browser-warning": "true", # Пропускает страницу-заглушку ngrok
#     "Content-Type": "application/json"     # Явно указываем тип данных
#     }

#     full_text = ""
#     try:
#         with requests.post(
#             f"{LLAMA_URL}/api/chat",
#             json=payload,
#             headers=headers,
#             stream=True,
#             timeout=120,          # ← увеличен до 120 сек
#         ) as resp:
#             resp.raise_for_status()
#             for line in resp.iter_lines():
#                 if not line:
#                     continue
#                 try:
#                     chunk = json.loads(line)
#                 except json.JSONDecodeError:
#                     continue
#                 token = chunk.get("message", {}).get("content", "")
#                 full_text += token
#                 yield token                       # отдаём токен в Streamlit
#                 if chunk.get("done"):
#                     break

#     except requests.exceptions.ConnectionError:
#         msg = "⚠️ Ollama не запущена. Выполни `ollama serve` в терминале."
#         yield msg
#         return {"text": msg, "action": None}
#     except requests.exceptions.Timeout:
#         msg = "⚠️ Модель не ответила. Попробуй ещё раз или перезапусти Ollama."
#         yield msg
#         return {"text": msg, "action": None}
#     except Exception as e:
#         msg = f"⚠️ Ошибка: {e}"
#         yield msg
#         return {"text": msg, "action": None}

#     # После стрима анализируем полный текст
#     raw = full_text.strip()
#     cmd = _extract_json(raw)
#     if cmd and cmd.get("action") == "navigate":
#         resolved_to   = _find_best_room(cmd.get("to"),   known_rooms)
#         resolved_from = _find_best_room(cmd.get("from"), known_rooms)
#         if resolved_to:
#             parts = ["Строю маршрут"]
#             if resolved_from:
#                 parts.append(f"от **{resolved_from}**")
#             parts.append(f"до **{resolved_to}**.")
#             text = " ".join(parts)
#             return {"text": text, "action": {"from": resolved_from, "to": resolved_to}}
#         else:
#             text = f"Не нашла кабинет «{cmd.get('to')}» в базе. Уточни название."
#             return {"text": text, "action": None}

#     return {"text": raw, "action": None}

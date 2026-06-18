"""
Тест логики нейрокомментинга без Telegram.
Проверяет: о чём пост → подходит ли → какой комментарий был бы.

Запуск (из корня репозитория):
  python test/test_comment.py
  python test/test_comment.py -t "текст"
  python test/test_comment.py -i
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

from openai import APIStatusError, AsyncOpenAI, RateLimitError

import neuro_config as cfg
from neuro_prompts import build_classify_system_prompt, build_comment_system_prompt

CLASSIFY_SYSTEM = build_classify_system_prompt()
COMMENT_SYSTEM = build_comment_system_prompt()

SAMPLE_POSTS: list[tuple[str, str]] = [
    (
        "Разбор сделки (подходит)",
        "Сегодня закрыл BTC в плюс: зашёл на 94к, первую половину зафиксировал на 97к, "
        "остаток держу с трейлингом. План был прописан заранее — без него начинаешь суетиться.",
    ),
    (
        "Обзор BTC (подходит)",
        "Еженедельный разбор: ключевая зона 91–93к. Удержим — ещё одна попытка на хай. "
        "Пробой вниз с объёмом — тест 86к. Пока без паники, смотрим реакцию на уровнях.",
    ),
    (
        "Розыгрыш (не подходит)",
        "🎁 Розыгрыш 1000 USDT! Подпишись, репостни и жми кнопку участвовать. "
        "Итоги через 3 дня, удачи всем!",
    ),
    (
        "Новость без аналитики (не подходит)",
        "Bitcoin обновил ATH. Подробности на сайте.",
    ),
]

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


async def _llm_request(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
) -> str | None:
    last_error = None
    for attempt in range(1, 4):
        try:
            response = await client.chat.completions.create(
                model=cfg.MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
        except (RateLimitError, APIStatusError) as e:
            last_error = e
            if getattr(e, "status_code", None) != 429 or attempt == 3:
                break
            await asyncio.sleep(attempt * 3)
        except Exception as e:
            last_error = e
            break
    print(f"Ошибка OpenRouter: {last_error}", file=sys.stderr)
    return None


def _parse_classification(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return {
            "suitable": bool(data.get("suitable")),
            "post_type": str(data.get("post_type", "—")),
            "reason": str(data.get("reason", "")),
            "raw": raw,
        }
    except json.JSONDecodeError:
        suitable = '"suitable": true' in text.lower() or '"suitable":true' in text.lower()
        return {
            "suitable": suitable,
            "post_type": "—",
            "reason": text[:200],
            "raw": raw,
        }


async def classify_post(post_text: str) -> dict:
    raw = await _llm_request(
        CLASSIFY_SYSTEM,
        f"Текст поста:\n{post_text}",
        max_tokens=200,
        temperature=0.2,
    )
    if not raw:
        return {"suitable": False, "post_type": "—", "reason": "ошибка API", "raw": ""}
    return _parse_classification(raw)


async def generate_comment(post_text: str) -> str | None:
    raw = await _llm_request(
        COMMENT_SYSTEM,
        f"Пост:\n{post_text}\n\nНапиши комментарий:",
        max_tokens=320,
        temperature=0.85,
    )
    if not raw:
        return None
    comment = raw.strip()
    if comment.startswith('"') and comment.endswith('"'):
        comment = comment[1:-1].strip()
    return comment or None


def _separator(title: str = "") -> None:
    print("\n" + "=" * 60)
    if title:
        print(title)
        print("=" * 60)


async def analyze_post(label: str, post_text: str) -> None:
    _separator(label or "Пост")
    preview = post_text.replace("\n", " ")
    if len(preview) > 200:
        preview = preview[:200] + "…"
    print(f"Текст: {preview}\n")

    print("⏳ Классификация…")
    clf = await classify_post(post_text)

    print(f"Тип поста:    {clf['post_type']}")
    print(f"О чём:        {clf['reason']}")
    print(f"Подходит:     {'✅ да' if clf['suitable'] else '❌ нет'}")

    if clf["suitable"]:
        print("\n⏳ Генерация комментария…")
        comment = await generate_comment(post_text)
        if comment:
            print(f"\nКомментарий:\n{comment}")
        else:
            print("\nКомментарий: (не удалось сгенерировать)")
    else:
        print("\nКомментарий: (пропуск — пост не подходит)")


async def run_samples() -> None:
    print(f"Модель: {cfg.MODEL}")
    print(f"Примеров: {len(SAMPLE_POSTS)}")
    for label, text in SAMPLE_POSTS:
        await analyze_post(label, text)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Тест нейрокомментинга (без Telegram)")
    parser.add_argument("-t", "--text", help="текст поста одной строкой")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="ввести текст поста в консоли"
    )
    args = parser.parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY не задан в .env")
        sys.exit(1)

    if args.text:
        await analyze_post("Свой пост", args.text)
        return

    if args.interactive:
        print("Вставьте текст поста. Завершите ввод: Ctrl+Z затем Enter (Windows) или Ctrl+D (Linux)")
        print("-" * 40)
        text = sys.stdin.read().strip()
        if not text:
            print("Пустой ввод.")
            sys.exit(1)
        await analyze_post("Интерактивный пост", text)
        return

    await run_samples()


if __name__ == "__main__":
    asyncio.run(main())

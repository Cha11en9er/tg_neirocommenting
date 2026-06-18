"""
Простой тест OpenRouter: один вопрос — один ответ.
Запуск: python test/test_provider.py
"""
import os
import sys
import time

import neuro_config as cfg
from openai import OpenAI, APIStatusError, RateLimitError

MODEL = cfg.MODEL
QUESTION = "какая погода в Пекине?"


def main() -> None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY не задан в .env")
        sys.exit(1)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/local/neirocommenting",
            "X-Title": "Neirocommenting Test",
        },
    )

    print(f"Модель: {MODEL}")
    print(f"Вопрос: {QUESTION}\n")

    last_error = None
    for attempt in range(1, 6):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": QUESTION}],
                max_tokens=256,
                temperature=0.7,
            )
            break
        except (RateLimitError, APIStatusError) as e:
            last_error = e
            if getattr(e, "status_code", None) != 429:
                print(f"Ошибка API:\n{e}")
                sys.exit(1)
            wait = attempt * 3
            print(f"Лимит запросов (попытка {attempt}/5), ждём {wait} с...")
            time.sleep(wait)
    else:
        print(f"Ошибка API после повторов:\n{last_error}")
        sys.exit(1)

    answer = response.choices[0].message.content
    print("Ответ модели:")
    print(answer)
    if response.usage:
        print(
            f"\nТокены: prompt={response.usage.prompt_tokens}, "
            f"completion={response.usage.completion_tokens}"
        )


if __name__ == "__main__":
    main()

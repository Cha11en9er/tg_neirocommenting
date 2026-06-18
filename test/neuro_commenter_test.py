"""
Тестовый бот — те же админ-команды и фризы, что у prod,
но с интервалами 5 мин (см. test/neuro_config.py).

Весь разбор LLM уходит в комментарий под постом (даже при 0 комментариев).

Запуск:
  python test/neuro_commenter_test.py
"""
import asyncio

import neuro_commenter


if __name__ == "__main__":
    print("🧪 Тестовый режим (интервалы 5 мин, config: test/neuro_config.py)")
    print("🧪 Разбор постов — в комментарии под постом, не в консоль")
    asyncio.run(neuro_commenter.main())

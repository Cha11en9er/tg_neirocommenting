# Развёртывание тестового бота на Ubuntu

Инструкция для сервера: клон репозитория, секреты, сессия Telegram-аккаунта и автозапуск через systemd.

> **Важно:** prod и test используют **одну** сессию (`neuro_session.session`). Не запускайте оба бота одновременно — ни на сервере, ни на ПК вместе с сервером.

---

## Что понадобится

| Что | Где лежит | В git? |
|-----|-----------|--------|
| Код | репозиторий | да |
| `.env` | корень проекта | **нет** — копируете с ПК |
| `neuro_session.session` | корень проекта | **нет** — копируете с ПК |
| `neuro_session.session-journal` | корень (если есть) | **нет** — копируете вместе с session |
| `test/channels.json` | список каналов | да (можно править на сервере) |
| `test/neuro_state_test.json` | состояние (фризы, обработанные посты) | **нет** — создаётся сам или копируется |

В `.env` должны быть:

```env
API_ID=...
API_HASH=...
PHONE=+7...
OPENROUTER_API_KEY=sk-or-v1-...
```

Получить `API_ID` / `API_HASH`: https://my.telegram.org/apps  
Ключ OpenRouter: https://openrouter.ai/keys

---

## 1. Подготовка сервера

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
python3 --version   # нужен Python 3.10+
```

Создайте пользователя для бота (рекомендуется, не root):

```bash
sudo adduser --disabled-password neurobot
sudo su - neurobot
```

Дальше команды — от имени этого пользователя (или своего, если уже не root).

---

## 2. Клонирование репозитория

```bash
cd ~
git clone https://github.com/Cha11en9er/tg_neirocommenting.git
cd tg_neirocommenting
```

Обновление в будущем:

```bash
cd ~/tg_neirocommenting
git pull
```

---

## 3. Виртуальное окружение и зависимости

```bash
cd ~/tg_neirocommenting
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

После `source venv/bin/activate` в начале строки появится `(venv)`.

---

## 4. Перенос `.env` и сессии Telegram с ПК

Файлы **не в git**. Скопируйте с Windows-машины на сервер через `scp` (выполнять **на ПК**, в PowerShell или Git Bash).

Подставьте свой логин и IP сервера:

```powershell
# из папки, где лежат .env и neuro_session.session (корень проекта на ПК)
scp .env neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/
scp neuro_session.session neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/
```

Если рядом с session есть journal-файл — тоже перенесите:

```powershell
scp neuro_session.session-journal neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/
```

На сервере проверьте права (чтобы другие пользователи не читали секреты):

```bash
cd ~/tg_neirocommenting
chmod 600 .env neuro_session.session
chmod 600 neuro_session.session-journal 2>/dev/null || true
ls -la .env neuro_session.session*
```

### Если сессии ещё нет

Один раз авторизуйтесь **на ПК**, запустите тестовый бот локально — Telethon создаст `neuro_session.session`. Потом скопируйте файл на сервер.

На сервере без готовой сессии первый запуск попросит код из Telegram; для headless-сервера это неудобно — проще всегда переносить уже авторизованную сессию.

### Опционально: состояние теста

Чтобы не потерять baseline обработанных постов и фризы:

```powershell
scp test/neuro_state_test.json neurobot@YOUR_SERVER_IP:~/tg_neirocommenting/test/
```

Если файла нет — бот создаст `test/neuro_state_test.json` при первом запуске.

---

## 5. Каналы и админ

Список каналов: `test/channels.json` (уже в репозитории). При необходимости отредактируйте на сервере или добавляйте каналы командой в личку боту:

```
https://t.me/username - . -GROUP_ID
```

Админ-команды (`статус`, `настройки`, `старт отправки` и т.д.) принимаются только от ID из `test/neuro_config.py` → `ADMIN_USER_IDS`. Свой Telegram ID можно узнать у [@userinfobot](https://t.me/userinfobot).

---

## 6. Пробный запуск

```bash
cd ~/tg_neirocommenting
source venv/bin/activate
python test/neuro_commenter_test.py
```

Ожидаемый вывод:

```
🧪 Тестовый режим (интервалы 5 мин, config: test/neuro_config.py)
🧪 Разбор постов — в комментарии под постом, не в консоль
✅ Нейрокомментер запущен! Аккаунт: @...
```

Остановка: `Ctrl+C`.

Поведение тестового бота:

- тик мониторинга каждые **5 минут**;
- разбор LLM уходит **в комментарий под постом** (в т.ч. при 0 комментариев);
- после комментария — заморозка канала на 5 минут.

---

## 7. Автозапуск через systemd

Создайте unit-файл (от root или через `sudo`):

```bash
sudo nano /etc/systemd/system/neuro-test.service
```

Содержимое (пути подставьте под своего пользователя):

```ini
[Unit]
Description=Telegram neuro commenting test bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=neurobot
WorkingDirectory=/home/neurobot/tg_neirocommenting
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/neurobot/tg_neirocommenting/venv/bin/python test/neuro_commenter_test.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Включить и запустить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable neuro-test
sudo systemctl start neuro-test
```

Полезные команды:

```bash
sudo systemctl status neuro-test      # статус
sudo journalctl -u neuro-test -f      # логи в реальном времени
sudo systemctl restart neuro-test     # перезапуск
sudo systemctl stop neuro-test          # остановка
```

---

## 8. Обновление после `git pull`

```bash
cd ~/tg_neirocommenting
git pull
source venv/bin/activate
pip install -r requirements.txt    # если менялись зависимости
sudo systemctl restart neuro-test
```

`.env`, `neuro_session.session` и `test/neuro_state_test.json` git **не трогает** — они останутся на месте.

---

## 9. Частые проблемы

### `SessionRevokedError` / просит войти снова

Сессия сброшена (вход с телефона, второй процесс с той же сессией). Остановите бота везде, заново авторизуйтесь на ПК, скопируйте свежий `neuro_session.session` на сервер.

### Бот на ПК и на сервере одновременно

Telethon держит одну активную сессию. Запускайте **только в одном месте**.

### `OPENROUTER_API_KEY` / ошибки LLM

Проверьте `.env`, баланс на OpenRouter, доступ сервера в интернет.

### Комментарии не появляются

- аккаунт должен быть участником канала и группы обсуждений;
- у канала включены комментарии;
- канал не в заморозке — команда `статус каналов` в личку боту;
- в логах: `journalctl -u neuro-test -n 100`.

### Кодировка в логах

В systemd обычно всё ок. При ручном запуске в старом терминале возможны кракозябры — на работу бота не влияет.

---

## 10. Чеклист перед продакшеном

- [ ] `.env` на сервере, права `600`
- [ ] `neuro_session.session` в **корне** репозитория
- [ ] `venv` создан, `pip install -r requirements.txt` без ошибок
- [ ] `test/channels.json` содержит нужные каналы
- [ ] Ваш ID в `ADMIN_USER_IDS`
- [ ] Бот **не** запущен на ПК
- [ ] `systemctl status neuro-test` → `active (running)`
- [ ] В логах нет повторяющихся ошибок API / Telegram

---

## Структура на сервере (итог)

```
/home/neurobot/tg_neirocommenting/
├── .env                          # секреты (с ПК)
├── neuro_session.session         # сессия TG-аккаунта (с ПК)
├── venv/                         # виртуальное окружение
├── test/
│   ├── neuro_commenter_test.py   # точка входа
│   ├── channels.json
│   └── neuro_state_test.json     # создаётся автоматически
└── ...
```

Запуск вручную: `python test/neuro_commenter_test.py` из корня репозитория с активированным `venv`.

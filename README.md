# Telegram Aggregator

SaaS-додаток для автоматичного агрегування та фільтрації повідомлень з Telegram-груп у цільовий канал.

---

## Зміст

1. [Як отримати API\_ID та API\_HASH](#1-як-отримати-api_id-та-api_hash)
2. [Як створити бота через @BotFather](#2-як-створити-бота-через-botfather)
3. [Локальний запуск](#3-локальний-запуск)
4. [Деплой на Railway](#4-деплой-на-railway)
5. [Supabase як база даних](#5-supabase-як-база-даних)
6. [Змінні середовища](#6-змінні-середовища)

---

## 1. Як отримати API\_ID та API\_HASH

1. Відкрийте [https://my.telegram.org](https://my.telegram.org) і увійдіть зі своїм номером телефону.
2. Перейдіть у розділ **API development tools**.
3. Заповніть форму (назва і короткий опис — будь-які).
4. Збережіть значення **App api\_id** (число) і **App api\_hash** (рядок).

> ⚠️ Не передавайте ці значення стороннім особам — вони прив'язані до вашого акаунта.

---

## 2. Як створити бота через @BotFather

1. Відкрийте Telegram і знайдіть [@BotFather](https://t.me/BotFather).
2. Надішліть `/newbot`.
3. Введіть назву бота (наприклад: `My Aggregator`).
4. Введіть username (наприклад: `my_aggregator_bot`).
5. Збережіть **токен** виду `123456:ABC-DEF1234...` — це `BOT_TOKEN`.

**Налаштування Telegram Login Widget:**

1. Надішліть BotFather команду `/setdomain`.
2. Оберіть вашого бота.
3. Введіть домен вашого сайту (наприклад: `my-app.up.railway.app`).

**У `frontend/index.html` замініть:**
```javascript
window.TG_BOT_USERNAME = 'YOUR_BOT_USERNAME';
```
або додайте мета-тег у `<head>`:
```html
<meta name="tg-bot" content="your_bot_username">
```

---

## 3. Локальний запуск

### Вимоги
- Python 3.11+
- PostgreSQL (або Supabase)

### Кроки

```bash
# 1. Клонуйте репозиторій
git clone <your-repo>
cd telegram-aggregator

# 2. Створіть віртуальне середовище
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# 3. Встановіть залежності
pip install -r requirements.txt

# 4. Скопіюйте та заповніть .env
cp .env.example .env
# Відредагуйте .env своїми значеннями

# 5. Згенеруйте ENCRYPTION_KEY (виконайте один раз)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Скопіюйте результат у .env як ENCRYPTION_KEY

# 6. Виконайте міграції
alembic upgrade head

# 7. Запустіть сервер
uvicorn backend.main:app --reload --port 8000
```

Відкрийте [http://localhost:8000](http://localhost:8000)

---

## 4. Деплой на Railway

### Крок 1: Підготовка репозиторію

```bash
git init
git add .
git commit -m "Initial commit"
# Завантажте на GitHub
```

### Крок 2: Створення проєкту в Railway

1. Відкрийте [railway.app](https://railway.app) та увійдіть.
2. Натисніть **New Project** → **Deploy from GitHub repo**.
3. Оберіть ваш репозиторій.

### Крок 3: Додайте PostgreSQL

1. У проєкті натисніть **+ New** → **Database** → **Add PostgreSQL**.
2. Railway автоматично додасть змінну `DATABASE_URL`.

> ⚠️ Railway надає URL у форматі `postgresql://...`. Для asyncpg потрібен `postgresql+asyncpg://...`
> Перейдіть у **Variables** та змініть `DATABASE_URL`, замінивши `postgresql://` на `postgresql+asyncpg://`.

### Крок 4: Змінні середовища

У вкладці **Variables** вашого сервісу додайте:

| Змінна | Значення |
|--------|----------|
| `TELEGRAM_API_ID` | Ваш API ID з my.telegram.org |
| `TELEGRAM_API_HASH` | Ваш API Hash |
| `BOT_TOKEN` | Токен бота від @BotFather |
| `SECRET_KEY` | Випадковий рядок мін. 32 символи |
| `ENCRYPTION_KEY` | Fernet ключ (44 символи base64) |

Генерація ключів:
```bash
# SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# ENCRYPTION_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Крок 5: Міграції

У вкладці **Settings** → **Deploy** → **Pre-deploy command** вкажіть:
```
alembic upgrade head
```

### Крок 6: Деплой

Railway автоматично побудує Docker-образ і задеплоїть. Ваш URL буде виду `https://your-app.up.railway.app`.

---

## 5. Supabase як база даних

1. Зареєструйтесь на [supabase.com](https://supabase.com).
2. Створіть новий проєкт.
3. Перейдіть у **Settings** → **Database** → **Connection string**.
4. Оберіть **URI** режим.
5. Скопіюйте рядок підключення.

**Для продакшну** використовуйте **Transaction Pooler** (порт 6543):
- Перейдіть у **Settings** → **Database** → **Connection pooling**.
- Скопіюйте URL з Pooler.
- Замініть `postgresql://` на `postgresql+asyncpg://`.

Приклад:
```
DATABASE_URL=postgresql+asyncpg://postgres.xxxx:password@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

> 📝 Для Supabase також виконайте міграції:
> ```bash
> DATABASE_URL=your_url alembic upgrade head
> ```

---

## 6. Змінні середовища

| Змінна | Опис | Де взяти |
|--------|------|----------|
| `DATABASE_URL` | PostgreSQL connection string з `+asyncpg` | Railway / Supabase |
| `TELEGRAM_API_ID` | Числовий ID вашого Telegram app | my.telegram.org |
| `TELEGRAM_API_HASH` | Hash вашого Telegram app | my.telegram.org |
| `BOT_TOKEN` | Токен Telegram-бота | @BotFather |
| `SECRET_KEY` | Секрет для підпису JWT | `secrets.token_hex(32)` |
| `ENCRYPTION_KEY` | Fernet ключ для шифрування сесій | `Fernet.generate_key()` |

---

## Архітектура

```
Telegram Group → Telethon Userbot → message_handler.py
                                         ↓
                              Keyword filtering (PLUS/MINUS)
                                         ↓
                              Destination Channel
```

- **FastAPI** — REST API + статичний фронтенд
- **Telethon** — Telegram userbot (слухає групи, пересилає)
- **SQLAlchemy async + asyncpg** — асинхронна робота з PostgreSQL
- **Alembic** — міграції схеми БД
- **Fernet** — шифрування session strings у БД
- **JWT** — авторизація API запитів

---

## Ліцензія

MIT

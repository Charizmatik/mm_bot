# Inventory Market Maker

Production deployment through GitHub and Portainer is documented in
[`DEPLOYMENT.md`](DEPLOYMENT.md).

MVP спотового market-making бота для MEXC за логікою з `my_logic.md`. Backend працює на FastAPI/PostgreSQL/Alembic, UI — React, запуск — Docker Compose.

> **Увага:** торгівля має фінансовий ризик. Проєкт стартує з `DRY_RUN=true`: читає публічні ціни MEXC, але ордери симулює локально. Не перемикайте live-режим до перевірки параметрів, мінімальних розмірів ордера та API-ключа без права виведення коштів.

## Реалізована логіка

- Нульовий ІРБ: buy/sell розміщуються симетрично — по половині цільового спреду від best bid/ask.
- Додатний ІРБ: buy стоїть на `order_offset_pct` від bid, sell — на решту спреду від ask. Для від'ємного ІРБ напрямок дзеркальний.
- Лот задається у quote-активі (наприклад USDT), кількість base-активу розраховується окремо для кожної ціни.
- Якщо обидва ордери виконані — цикл фіксується як прибутковий, ІРБ не змінюється.
- Якщо виконаний BUY і ринок падає за red line — SELL скасовується, ІРБ зменшується. Після SELL і руху вгору — ІРБ збільшується.
- Для кожного активу пари задаються фіксовані `balance_trigger` і `balance_limit` у одиницях самого активу. На trigger створюється подія про ручне балансування; на limit відкриті ордери скасовуються й торгівля зупиняється.
- Після red line бот чекає `pause_minutes`, потім створює новий цикл.
- Під час старту відкритий цикл і його ордери завантажуються з БД, статуси повторно перевіряються на MEXC.
- Для кожного виконаного ордера зберігаються фактичні fills і комісії MEXC. Gross P&L враховує quote cash flow та ринкову вартість зміни base inventory на момент закриття; net P&L дорівнює gross мінус комісії.
- Статистика показує кількість успішних циклів, red-line циклів, success rate, gross profit, комісії та net profit окремо за quote-активом.
- Ручна зупинка скасовує відкриті ордери. ІРБ вручну змінюється лише для зупиненої пари й з обов'язковою приміткою в журналі.

## Запуск

1. Скопіюйте `.env.example` у `.env`.
2. Для першого запуску залиште `DRY_RUN=true`.
3. Запустіть:

```powershell
docker compose up --build
```

4. Відкрийте `http://localhost:8080`. Swagger API доступний на `http://localhost:8000/docs`.

### Запуск через Makefile

Для першого запуску:

```powershell
make setup
```

Наступні запуски та робота з БД:

```powershell
make up
make migrate
make migration-check
make test
make logs
make down
```

Повний список команд показує `make help`. Нова міграція створюється командою
`make revision MSG="опис зміни"`. Команда `make down` не видаляє PostgreSQL volume.

Для live-режиму створіть MEXC API-ключ лише з правами читання та spot trading, без withdrawal, внесіть ключі у `.env` і встановіть `DRY_RUN=false`.

## Параметри

- Відсоткові поля вводяться як звичайні проценти: `0.15` означає 0,15%.
- `PAPER_MAKER_FEE_PCT` задає симульовану maker-комісію для dry-run; типове початкове значення — `0.1`.
- `base_balance_trigger` / `base_balance_limit` задаються у base-активі, наприклад BTC.
- `quote_balance_trigger` / `quote_balance_limit` задаються у quote-активі, наприклад USDT.
- Усі чотири пороги — фіксовані значення, не відсотки. Trigger має бути більшим за відповідний limit.
- `price_precision` і `quantity_precision` задають кількість знаків; ціни та кількості округлюються вниз відповідно до прикладів у `my_logic.md`.
- Символ нормалізується до формату MEXC (`BTC_USDT` → `BTCUSDT`).

## Розробка й тести

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest
```

Frontend:

```powershell
cd frontend
npm install
npm run build
```

## Межі MVP

- Реальні баланси читаються адаптером, але UI ще не рахує фактичну вагу портфеля — контроль inventory виконується через ІРБ, як описано у вихідній логіці.
- Dry-run використовує REST book ticker раз на секунду; live-режим використовує новий protobuf WebSocket MEXC. Статуси приватних ордерів перевіряються REST polling.
- У live-режимі комісії читаються з MEXC `myTrades`. Якщо комісія сплачена не в quote-активі, бот конвертує її за поточним book ticker відповідної пари.
- Перед live потрібна перевірка exchange filters (`minNotional`, крок ціни та кількості) для кожної конкретної пари.

## Додавання іншої біржі

Реалізуйте інтерфейс `backend/app/exchanges/base.py` і виберіть адаптер у `backend/app/main.py`. Стратегія та API від біржі не залежать.

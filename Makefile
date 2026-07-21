COMPOSE := docker compose
BACKEND_MOUNT := --volume "$(CURDIR)/backend:/app"

.DEFAULT_GOAL := help

.PHONY: help setup env build build-backend up start stop down restart ps logs backend-logs \
	db migrate migration-check migration-current migration-history revision test health db-shell

help: ## Показати доступні команди
	@echo "Inventory Market Maker"
	@echo ""
	@echo "  make setup              Перший запуск: env, build, контейнери, міграції"
	@echo "  make up                 Зібрати та запустити весь стек"
	@echo "  make start              Запустити вже зібрані контейнери"
	@echo "  make stop               Зупинити контейнери без видалення"
	@echo "  make down               Зупинити й видалити контейнери (дані БД лишаються)"
	@echo "  make restart            Перезапустити стек"
	@echo "  make migrate            Застосувати всі Alembic-міграції"
	@echo "  make migration-check    Перевірити відповідність моделей і схеми БД"
	@echo "  make migration-current  Показати поточну версію БД"
	@echo "  make migration-history  Показати історію міграцій"
	@echo "  make revision MSG=...   Створити autogenerate-міграцію"
	@echo "  make test               Запустити backend-тести у Docker"
	@echo "  make health             Перевірити health endpoint"
	@echo "  make logs               Стежити за логами всього стека"
	@echo "  make backend-logs       Стежити лише за backend-логами"
	@echo "  make db-shell           Відкрити psql"

setup: env migrate migration-check up ## Повний перший запуск

env: .env ## Створити .env з шаблону, якщо його немає

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example. Fill in MEXC credentials if needed."

build: ## Зібрати Docker-образи
	$(COMPOSE) build

build-backend: ## Зібрати лише backend-образ
	$(COMPOSE) build backend

up: env ## Зібрати й запустити весь стек у background
	$(COMPOSE) up --build -d

start: env ## Запустити вже зібраний стек
	$(COMPOSE) up -d

stop: ## Зупинити контейнери
	$(COMPOSE) stop

down: ## Видалити контейнери, але зберегти volume PostgreSQL
	$(COMPOSE) down

restart: ## Перезапустити весь стек
	$(COMPOSE) restart

ps: ## Показати стан контейнерів
	$(COMPOSE) ps

logs: ## Стежити за логами
	$(COMPOSE) logs -f --tail=150

backend-logs: ## Стежити за backend-логами
	$(COMPOSE) logs -f --tail=150 backend

db: env ## Запустити лише PostgreSQL і дочекатися healthcheck
	$(COMPOSE) up -d --wait postgres

migrate: build-backend db ## Застосувати всі міграції до head
	$(COMPOSE) run --rm backend alembic upgrade head

migration-check: build-backend db ## Перевірити, чи потрібна нова міграція
	$(COMPOSE) run --rm backend alembic check

migration-current: build-backend db ## Показати поточну ревізію БД
	$(COMPOSE) run --rm backend alembic current

migration-history: build-backend ## Показати повну історію Alembic
	$(COMPOSE) run --rm --no-deps backend alembic history --verbose

revision: build-backend db ## Створити міграцію: make revision MSG="опис"
	$(if $(strip $(MSG)),,$(error Usage: make revision MSG="migration description"))
	$(COMPOSE) run --rm $(BACKEND_MOUNT) backend alembic revision --autogenerate -m "$(MSG)"

test: build-backend ## Запустити unit-тести backend
	$(COMPOSE) run --rm --no-deps backend python -m pytest -q

health: ## Перевірити API всередині backend-контейнера
	$(COMPOSE) exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"

db-shell: ## Відкрити PostgreSQL CLI
	$(COMPOSE) exec postgres psql -U market_maker -d market_maker

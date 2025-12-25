# CLAUDE_NOTES.md — мои заметки по проекту

## Статус: взял в работу 25.12.2025

---

## Что это

CLI тул для семантического анализа git коммитов. Вместо "что изменилось" показывает:
- Intent — зачем
- Impact — на что влияет
- Risk — что может сломаться
- Questions — что спросить автора

Потенциально — продукт для Kenaz.

---

## Архитектура (текущая)

```
semantic_diff/
├── cli.py              # Click CLI
├── models.py           # Pydantic models
├── parsers/
│   └── git_parser.py   # GitPython, извлекает diff
├── analyzers/
│   └── llm_analyzer.py # Claude API call
└── formatters/
    └── console_formatter.py  # Rich output
```

Чистая структура. Нравится.

---

## БАГИ (известные, нефикшенные)

### 1. `'content' in dir()` — git_parser.py:104
```python
additions=len(content.split('\n')) if 'content' in dir() else 0
```
`dir()` возвращает имена в текущем scope, но это НЕ проверка существования переменной.
**Фикс:** использовать try/except или инициализировать content = "" до try блока.

### 2. Bare except — git_parser.py:98, 133
```python
except:
    diff_content = "[binary file]"
```
Ловит ВСЁ включая KeyboardInterrupt, SystemExit.
**Фикс:** `except Exception:` или конкретные типы.

### 3. sys.path.insert — cli.py:9-10
```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```
Костыль для dev. Не нужен если `pip install -e .`
**Фикс:** удалить, полагаться на правильную установку.

### 4. Нет retry для API — llm_analyzer.py
Если Claude упал, rate limit, timeout — всё умирает.
**Фикс:** tenacity или ручной retry с backoff.

### 5. Нет валидации JSON ответа — llm_analyzer.py
Если Claude вернёт неполный JSON — KeyError.
**Фикс:** валидация через Pydantic, graceful fallback.

---

## НЕДОСТАТКИ (архитектурные)

1. **Нет тестов** — pytest в зависимостях, тестов нет
2. **Нет кэширования** — каждый раз API call даже для того же коммита
3. **Нет batch mode** — нельзя `semantic-diff HEAD~5..HEAD`
4. **Prompt hardcoded** — нельзя кастомизировать
5. **Только Anthropic** — нет GPT, Gemini, local models
6. **Нет CI/CD интеграции** — нет GitHub Action, pre-commit hook
7. **Нет storage** — результаты не сохраняются

---

## СТРАТЕГИЧЕСКИЕ ВОПРОСЫ

### Позиционирование

**Вариант A: Developer CLI tool**
- Личный помощник для code review
- `brew install semantic-diff`
- Freemium: 10 анализов/день бесплатно

**Вариант B: CI/CD Integration**
- GitHub Action
- GitLab CI
- Auto-comment на PR
- Платная подписка per-repo

**Вариант C: Security Focus**
- Упор на risk assessment
- Интеграция с vulnerability databases
- Compliance reports
- Enterprise pricing

**Вариант D: Code Review Platform**
- Web UI
- Team features
- История анализов
- SaaS модель

### Моя рекомендация

Начать с **A** (CLI tool), добавить **B** (GitHub Action) как второй шаг.
Это даёт:
- Быстрый time-to-market
- Organic growth через developers
- Upsell path в enterprise

---

## ПЛАН РАБОТЫ

### Phase 1: Стабилизация (сейчас)
- [ ] Пофиксить все известные баги
- [ ] Добавить retry логику
- [ ] Добавить валидацию ответа LLM
- [ ] Базовые тесты

### Phase 2: Продуктизация
- [ ] Кэширование результатов (SQLite или JSON)
- [ ] Batch mode (диапазон коммитов)
- [ ] GitHub Action
- [ ] Конфигурация через `.semantic-diff.yaml`

### Phase 3: Growth
- [ ] Homebrew formula
- [ ] PyPI publish
- [ ] Документация
- [ ] Landing page

---

## СЕССИЯ 25.12.2025

### Сделано:
- [x] Баг `'content' in dir()` — пофикшен (git_parser.py)
- [x] Bare except — пофикшены оба (git_parser.py)
- [x] sys.path.insert костыль — удалён (cli.py)
- [x] Retry логика для API — добавлен `_call_api_with_retry` (llm_analyzer.py)
- [x] Валидация JSON ответа — добавлен `_validate_response_data` (llm_analyzer.py)
- [x] **Протестировал на себе** — semantic-diff проанализировал свой же коммит!
- [x] Jitter добавлен в retry (thundering herd fix)
- [x] Retry-After header support
- [x] max_total_wait limit (30s default)
- [x] max_retries configurable через SEMANTIC_DIFF_MAX_RETRIES
- [x] Logging когда defaults применяются
- [x] Auto-reduce confidence когда критические поля missing

### Meta-insight:
Инструмент нашёл баги в самом себе. Дважды. Второй раз — в том, что я пофиксил в первый раз.
Это валидация концепции — он реально полезен для iterative development.

### Итоговые фиксы сессии:
- Retry-After header parsing с fallback на exponential backoff
- max_total_wait теперь configurable через SEMANTIC_DIFF_MAX_WAIT
- Все известные баги закрыты

### Стратегическое решение:
**Фаза 1** — CLI tool (Homebrew, PyPI, freemium)
**Фаза 2** — GitHub Action (auto-comment на PR, $19/repo/month)

### Следующие шаги:
- [ ] Тесты (pytest)
- [ ] Кэширование результатов
- [ ] Batch mode (диапазон коммитов)
- [ ] GitHub Action MVP
- [ ] Landing page на kenaz.ai

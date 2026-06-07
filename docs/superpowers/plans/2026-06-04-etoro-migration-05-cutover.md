# eToro Migration — Plan 5: Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make eToro the *only* broker — delete the Alpaca client, dependency, env, and code paths; collapse the provider plumbing to eToro; lay down a fresh eToro-only trades schema; update the GPT prompts for eToro-native crypto symbols; and fix the two pre-existing test failures so the whole suite is green.

**Architecture:** Subtractive. The eToro broker, data, universe, and trade lifecycle are already live and tested (Plans 1–4). This plan removes the now-unused Alpaca scaffolding, renames the single remaining provider default from `PROVIDER_ALPACA` to `PROVIDER_ETORO` everywhere, and deletes Alpaca-specific methods. Two unrelated pre-existing test failures (a missing report JSON sidecar; an incomplete `gpt_client` test stub) are fixed. Because the project is a clean slate (DBs wiped on deploy), the trades schema is rewritten without the `alpaca_*`/`client_order_id`/`exit_client_order_id`/`broker_protection_*` columns rather than migrated.

**Tech Stack:** Python 3.11+, `unittest` in Docker. Verify with `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests`.

**Depends on:** Plans 1–4.

**Verification cadence:** after Tasks 3, 5, 6, 7 run an import smoke test in Docker — `python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('**/*.py', recursive=True)]; print('all parse')"` — then the full suite at the end. The goal end-state is a green `python -m unittest discover -s tests` (no failures, no errors).

---

## Task 1: Fix `test_scheduler_api` (incomplete gpt_client stub)

`api_server.py` does `from clients.gpt_client import get_default_prompts`, but the test's module-level stub only defines `GPTClient`, so the import fails.

**Files:** `tests/test_scheduler_api.py`

- [ ] **Step 1: Add the missing attribute to the stub**

In `tests/test_scheduler_api.py`, find the `gpt_client` stub creation (a `ModuleType("clients.gpt_client")` with `GPTClient` set) and add a `get_default_prompts` callable before the `sys.modules.setdefault(...)` line:

```python
gpt_client_stub.get_default_prompts = lambda: {}
```

(If the test builds the stub inline, add the attribute next to `gpt_client_stub.GPTClient = object`.)

- [ ] **Step 2: Verify**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_scheduler_api`
Expected: OK (or a real assertion result, not an ImportError).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_scheduler_api.py
git commit -m "test: complete gpt_client stub in test_scheduler_api"
```

---

## Task 2: Fix `test_report` (restore JSON report sidecar)

`report_index` indexes both `.json` and `.pdf` reports, but `generate_weekly_report`/`_generate_period_report` only write the PDF, so the documented JSON report is missing (and the test that asserts a JSON + PDF fails). Write the JSON sidecar.

**Files:** `services/report.py`

- [ ] **Step 1: Import the JSON writer**

In `services/report.py`, add to the `from core.utils import …` line: `write_json_file` (so it reads `from core.utils import AppConfig, utc_now, write_json_file`).

- [ ] **Step 2: Write the JSON in `generate_weekly_report`**

In `generate_weekly_report`, after `pdf_path = … .pdf` and before/after `_render_pdf_report`, add:

```python
        json_path = report_dir / f"weekly_report_{stamp}.json"
        write_json_file(json_path, report)
```

- [ ] **Step 3: Write the JSON in `_generate_period_report`**

In `_generate_period_report`, after `pdf_path = … .pdf`, add:

```python
        json_path = report_dir / f"{report_type}_report_{slug}_{stamp}.json"
        write_json_file(json_path, report)
```

- [ ] **Step 4: Verify**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_report`
Expected: OK (JSON + PDF written → 2 files).

- [ ] **Step 5: Commit**

```bash
git add backend/services/report.py
git commit -m "fix(reports): write JSON sidecar alongside the PDF report"
```

---

## Task 3: Fresh eToro-only trades schema

**Files:** `core/db.py`, `core/app_db.py`, `tests/test_etoro_trade_schema.py`

- [ ] **Step 1: Strengthen the schema test**

In `tests/test_etoro_trade_schema.py`, add assertions that the legacy columns are gone:

```python
            for legacy in ("alpaca_order_id", "client_order_id", "exit_client_order_id",
                           "broker_protection_type", "protection_order_id", "protection_client_order_id"):
                self.assertNotIn(legacy, cols)
            # provider defaults to etoro
            conn = sqlite3.connect(trades)
            conn.execute("INSERT INTO trades (symbol, category, status, entry_price, quantity, allocated_capital) "
                         "VALUES ('AAPL','STOCK','PENDING',1,1,1)")
            row = conn.execute("SELECT provider FROM trades").fetchone()
            conn.close()
            self.assertEqual(row[0], "etoro")
```

- [ ] **Step 2: Rewrite `TRADES_SCHEMA`**

In `core/db.py`, edit `TRADES_SCHEMA`: remove the lines `alpaca_order_id TEXT,`, `client_order_id TEXT,`, `exit_client_order_id TEXT,`; change `provider TEXT NOT NULL DEFAULT 'alpaca'` to `provider TEXT NOT NULL DEFAULT 'etoro'`. Keep `exit_order_id TEXT` and the new `instrument_id`/`position_id`/`order_reference_id`.

- [ ] **Step 3: Trim `TRADE_OPTIONAL_COLUMNS`**

In `core/db.py`, remove the `broker_protection_type`, `protection_order_id`, `protection_client_order_id`, `exit_client_order_id` entries from `TRADE_OPTIONAL_COLUMNS`, and change the `provider` default to `'etoro'`.

- [ ] **Step 4: Snapshot provider default**

In `core/app_db.py`, change the two `account_equity_snapshots` `provider TEXT NOT NULL DEFAULT 'alpaca'` occurrences (schema + ALTER, lines ~90 and ~176) to `'etoro'`.

- [ ] **Step 5: Verify**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_etoro_trade_schema`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add backend/core/db.py backend/core/app_db.py backend/tests/test_etoro_trade_schema.py
git commit -m "feat(etoro): fresh eToro-only trades schema (drop alpaca columns)"
```

---

## Task 4: Delete the Alpaca client, dependency, env, and wiring

**Files:** `clients/alpaca_client.py` (delete), `requirements.txt`, `backend/.env.example`, `main.py`

- [ ] **Step 1: Delete the client and dependency**

```bash
git rm backend/clients/alpaca_client.py
```
In `backend/requirements.txt`, delete the `alpaca-py` line.

- [ ] **Step 2: Remove ALPACA_* from `.env.example`**

In `backend/.env.example`, delete the `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`/`ALPACA_BASE_URL`/`ALPACA_ACCOUNT_CURRENCY`/`ALPACA_MAX_NOTIONAL_PER_ORDER` lines and their comment block (keep the OpenAI block and the eToro block).

- [ ] **Step 3: Remove Alpaca from `main.py`**

In `main.py`, delete `from clients.alpaca_client import AlpacaClient`, remove `PROVIDER_ALPACA` from the `core.utils` import, and delete the `if config.alpaca_enabled: brokers[PROVIDER_ALPACA] = AlpacaClient(...) … else: …` block (keep the eToro block).

- [ ] **Step 4: Verify import smoke test**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -c "import ast; ast.parse(open('main.py').read()); print('main parses')"`
Expected: `main parses` (note: full `import main` is exercised at the end once Task 5/6 land).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(etoro): remove Alpaca client, dependency, env, and main wiring"
```

---

## Task 5: Collapse provider plumbing in `core/utils.py`

**Files:** `core/utils.py`

- [ ] **Step 1: Remove the constant and Alpaca config**

In `core/utils.py`:
- Delete the `PROVIDER_ALPACA = "alpaca"` line; keep `PROVIDER_ETORO = "etoro"`. Set `ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ETORO,)`.
- In `AppConfig`, delete the fields `alpaca_api_key`, `alpaca_secret_key`, `alpaca_base_url`, `alpaca_max_notional_per_order`; make the remaining required fields have defaults (e.g. keep `openai_api_key: str`). Delete the `paper` and `alpaca_enabled` properties.
- In `active_providers`, drop the alpaca branch (return `(PROVIDER_ETORO,)` when `etoro_enabled` else `()`).
- In `_empty_universe`, drop the alpaca entry (eToro only).
- In `_normalize_universe_payload`, change the legacy-flat fallback to populate `PROVIDER_ETORO` instead of `PROVIDER_ALPACA`.
- In `SETTINGS_OVERRIDABLE_KEYS`, remove `alpaca_max_notional_per_order`.
- In `load_config`, delete the `alpaca_api_key`/`alpaca_secret_key`/`alpaca_base_url`/`alpaca_max_notional_per_order` kwargs and the `account_currency` ALPACA alias (set `account_currency="USD"` directly).

- [ ] **Step 2: Update the test constructors**

The eToro tests build `AppConfig(openai_api_key=…, alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x", …)`. With those fields removed, update every test helper that constructs `AppConfig` to drop the three alpaca kwargs. Affected: `tests/test_etoro_config.py`, `tests/test_etoro_client.py`, `tests/test_etoro_equity_snapshots.py`, `tests/test_etoro_universe.py`, `tests/test_trade_manager_etoro.py`, `tests/test_report.py`, `tests/test_scheduler_api.py`, `tests/test_data_manager.py` (grep: `grep -rl alpaca_api_key tests/`).

- [ ] **Step 3: Verify**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_etoro_config tests.test_etoro_universe`
Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(etoro): collapse provider plumbing to eToro-only in core/utils"
```

---

## Task 6: Remove Alpaca paths across services + API

For each file: change `from core.utils import PROVIDER_ALPACA` → `PROVIDER_ETORO` (or drop if unused), replace remaining `PROVIDER_ALPACA` identifiers with `PROVIDER_ETORO`, delete `alpaca_client` properties / `alpaca_client=` kwargs / single-broker compat branches, and delete Alpaca-specific methods.

**Files:** `services/data_manager.py`, `services/trade_manager.py`, `services/universe_manager.py`, `services/universe_admin.py`, `services/metrics_service.py`, `services/equity_snapshots.py`, `services/trade_admin.py`, `api/api_server.py`

- [ ] **Step 1: `data_manager.py`** — drop the `alpaca_client` property + `alpaca_client=` kwarg + `{"alpaca": …}` compat; default `provider="alpaca"` in `update_symbol`/`_unpack_value` → `"etoro"`.

- [ ] **Step 2: `trade_manager.py`** — drop the `alpaca_client` property + `alpaca_client=` kwarg + `{PROVIDER_ALPACA: …}` compat; replace `PROVIDER_ALPACA` (default params, `_trade_provider` fallback, `evaluate_cycle` legacy-flat branch) with `PROVIDER_ETORO`.

- [ ] **Step 3: `universe_manager.py`** — delete `_select_alpaca_universe`, `_get_alpaca_stock_candidate_payload`, `_get_alpaca_crypto_candidate_payload`, the `alpaca_client` property, the `alpaca_client=` kwarg and `{PROVIDER_ALPACA: …}` compat; in `select_trading_universe` remove the alpaca branch (eToro only); replace remaining `PROVIDER_ALPACA` with `PROVIDER_ETORO`.

- [ ] **Step 4: `universe_admin.py`** — drop `PROVIDER_ALPACA` from the categories map and validation branches (the eToro branch already short-circuits; remove the trailing Alpaca catalogue-scan block and the Alpaca crypto `BASE/QUOTE` branch in `_normalize_symbol`); default provider in `_normalize_provider` → `PROVIDER_ETORO`.

- [ ] **Step 5: `metrics_service.py`** — drop the `alpaca_client` property + `{PROVIDER_ALPACA: …}` compat branch + `alpaca_client=` kwarg; replace the `or PROVIDER_ALPACA` fallbacks (lines ~159, ~235, ~496, ~541) with `or PROVIDER_ETORO`; update the import.

- [ ] **Step 6: `equity_snapshots.py`** — change the `from core.utils import PROVIDER_ALPACA` to `PROVIDER_ETORO`; default `provider` params and `str(row.get("provider") or PROVIDER_ALPACA)` → `PROVIDER_ETORO`.

- [ ] **Step 7: `trade_admin.py`** — line ~139 reads `before.get("alpaca_order_id")`; change to `before.get("position_id")` (the eToro handle) or drop the broker-cancel branch if it only logged.

- [ ] **Step 8: `api_server.py`** — change the `PROVIDER_ALPACA` import → `PROVIDER_ETORO`; line ~1071 default provider and ~1130 → `PROVIDER_ETORO`; lines ~929–930 remove `alpaca_api_key`/`alpaca_secret_key` from whatever settings/secret list they appear in.

- [ ] **Step 9: Verify parse + targeted suites**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('**/*.py', recursive=True)]; print('all parse')"
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_trade_manager_etoro tests.test_etoro_universe tests.test_data_manager
```
Expected: `all parse`, then OK.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(etoro): remove Alpaca code paths across services and API"
```

---

## Task 7: eToro-native GPT prompts

**Files:** `clients/gpt_client.py`, `core/app_db.py`

The universe/signal prompts instruct the model to use "Alpaca pair format like BTC/<currency>". eToro uses native crypto tickers (e.g. `BTC`). Update the wording and provider defaults.

- [ ] **Step 1: Update crypto-format wording**

In `clients/gpt_client.py`, change each occurrence (lines ~356, ~365, ~378, ~394, ~407) of "Alpaca pair format like BTC/<currency>" / "Alpaca pair symbols quoted in that currency" / "provided Alpaca candidate list" to eToro-native phrasing, e.g. "use eToro native crypto tickers like BTC (no quote-currency suffix)" and "use only the provided candidate list for this batch".

- [ ] **Step 2: Rename provider defaults + prompt keys**

In `clients/gpt_client.py`, change the `provider: str = "alpaca"` default params (lines ~488, ~526, ~543) to `provider: str = "etoro"`, and rename `_alpaca_prompt_keys` → `_prompt_keys` (update its caller). In `core/app_db.py`, rename `ALPACA_PROMPT_KEYS` → `PROMPT_KEYS` (and the `PROMPT_KEYS = ALPACA_PROMPT_KEYS` alias collapses to one definition); update references via `grep -rn ALPACA_PROMPT_KEYS`.

- [ ] **Step 3: Verify**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests 2>&1 | tail -6`
Expected: a single OK across the whole suite (no failures, no errors).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(etoro): eToro-native crypto wording and provider defaults in prompts"
```

---

## Task 8: Final verification + demo integration readiness

- [ ] **Step 1: Whole suite green**

Run: `docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests 2>&1 | tail -6`
Expected: `OK` — zero failures, zero errors.

- [ ] **Step 2: No Alpaca residue**

Run: `grep -rniE "alpaca" backend --include=*.py | grep -v tests/ || echo "no alpaca references"`
Expected: only intentional historical comments (e.g. `core/fx.py` docstring) — no code references. Clean those comments if trivial.

- [ ] **Step 3: Live demo smoke (requires credentials — operator-run)**

This step needs real eToro keys and a Demo account; it is run by the operator, not in CI. With `backend/.env` containing `ETORO_API_KEY`, `ETORO_USER_KEY`, `ETORO_ACCOUNT_TYPE=demo`, run a read-only probe (resolve an instrument + fetch the demo portfolio) to confirm connectivity before enabling the scheduler. Document the exact command in the PR description. Do NOT place orders as part of verification.

---

## Self-Review (completed during planning)

- **Spec coverage (Plan 5 / cutover):** remove Alpaca client/dep/env/wiring (§5.8) — Tasks 4, 6 ✓; fresh eToro-only DB schema dropping `alpaca_*` columns (§5.6) — Task 3 ✓; collapse providers to eToro (§5.5) — Tasks 5, 6 ✓; eToro-native crypto symbols end-to-end incl. GPT prompts (§2 decision 6) — Task 7 ✓; demo-first integration readiness (§8 build-seq step 8) — Task 8 ✓. The two pre-existing, broker-agnostic test failures are fixed (Tasks 1, 2) so the suite is fully green.
- **Risk control:** subtractive change verified by an all-files `ast.parse` smoke test after the structural removals (Tasks 4, 6) and a full-suite run after Tasks 5, 6, 7 — catching any missed `PROVIDER_ALPACA` reference immediately (it would be a `NameError`/`ImportError` at parse/import).
- **Placeholder scan:** none. File/line hints (e.g. metrics_service ~159/235/496/541, gpt_client ~356–407) are exact pointers verified against the current source.
- **Type consistency:** every removed `PROVIDER_ALPACA` becomes `PROVIDER_ETORO` (same `str` type); `AppConfig` loses only Alpaca fields (tests updated in Task 5 Step 2 to match the new constructor); report JSON uses the existing `write_json_file(path, dict)` helper.

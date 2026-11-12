# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

StorageWeb is a Flask + Waitress file server (upload/download) with local, PAM and Microsoft Entra ID (OAuth2/OIDC or MSAL) users, SQLite storage and a web admin. The project language is **Spanish**: docs (`docs/`, MkDocs), code comments, commit messages and the user conversation. UI/CLI source strings are **English** and translated to Spanish via gettext.

## Commands

On this Windows machine use the venv interpreter directly: `.venv/Scripts/python` (Linux/macOS: `.venv/bin/python`).

```bash
pip install -e ".[dev,docs]"                                   # setup
python -m storageweb --config config/config.dev.json serve --dev   # dev server, auto-reload, http://127.0.0.1:8080
python -m storageweb --config config/config.dev.json user-add ana --role admin   # dev user

python -m pytest -q                                            # all tests (~3 min)
python -m pytest -q tests/unit                                 # fast subset
python -m pytest -q tests/integration/test_groups.py -k matrix # single file / test

python tools/i18n.py update      # re-extract strings into messages.pot and es/messages.po
python tools/i18n.py check       # fails on untranslated/obsolete strings (CI + test_i18n)
python tools/gen_docs.py         # regenerate docs/referencia/{configuracion,cli,api}.md
python tools/gen_docs.py --check
mkdocs build --strict
```

The pre-PR checklist (CONTRIBUTING.md) is: pytest, `gen_docs.py --check`, `i18n.py check`, `mkdocs build --strict`, plus an entry under *Sin publicar* in `CHANGELOG.md`. The same VS Code tasks exist in `.vscode/tasks.json`. Do not use Docker on this PC (it does not work here); `Dockerfile`/`compose.yaml` are only validated in CI.

## Architecture

Layering under `src/storageweb/` (enforced by review, see CONTRIBUTING.md): `web → core → db/providers → settings`. **Only `web/` imports Flask.** Repositories in `db/repositories/` are plain functions taking a `sqlite3.Connection` as first argument; business rules live in `core/`.

- **Settings**: `config.json` is loaded and validated by `settings/loader.py` (defaults and per-field documentation in `settings/defaults.py`; that documentation feeds `gen_docs.py`). Sections editable from the web are stored as a JSON document in the SQLite `settings` table and override the file (`RuntimeSettings`, `runtime_view()`); `web/context.py` exposes `settings()`, `runtime()` and `get_db()` per request. Changing a config field means updating defaults, loader validation, the admin settings form (`web/views/admin.py::_runtime_from_form` rebuilds `storage.shares` from form lists — keep hidden inputs for fields the form doesn't show) and regenerating the reference docs.
- **Migrations**: `db/migrations/NNN_*.sql`, applied at app start with `PRAGMA user_version`. **Never edit a migration once any database may have applied it** — the dev server applies new ones to `.dev/data/storageweb.db` immediately, so even unreleased migrations are frozen once the server ran. Add a new numbered file instead.
- **Auth**: `core/accounts.py` handles password login (local/PAM), SSO claims (`login_with_claims`: tenant/group checks, auto-provisioning, role mapping) and admin guards (last active admin, no self-demotion/disable). SSO providers implement `providers/base.py`; the default `oauth2` provider is stdlib-only (PKCE, no id_token signature check by design, see ADR 0004).
- **Groups** (`core/groups.py`, ADR 0011): tables `groups` + `user_groups` with `origin` = `manual`|`sync`. Logins only replace `sync` memberships of the user's source. `users.groups` is a denormalized **effective** list (`users.external_groups` from the IdP ∪ member group names) used by `core/storage.available_roots` for share access — always change memberships through `core/groups`, which calls `refresh_user`. The builtin `admins` group has no rows in `user_groups`: membership = `role == 'admin'`, added at request time in `available_roots`. Per-group read-only access is `storage.shares[].read_only_groups`.
- **Files**: `core/storage.py` (roots, listing, `explain_access`), `core/security.py` (`resolve_inside`, `safe_filename` — every user-supplied path/name must pass through them), `core/permissions.py` (role permissions; read-only roots only allow download). Large uploads use the resumable chunk API in `web/api/uploads.py` + `core/uploads.py` (`.sw-upload-<id>.part` files); downloads support Range.
- **Web**: blueprints in `web/views/` (`auth`, `files`, `admin`, `groups`, `profile`) and `web/api/`. `guards.py` provides session loading, locale selection, CSRF (form `_csrf` or `X-CSRF-Token` header), `admin_required`, `safe_next`. The CSP forbids inline scripts/styles: JS goes in `web/static/js/*.js`, data to JS via `<script type="application/json">`.
- **Audit**: relevant actions call `audit.log(...)`. Every action name used in code must be listed in `docs/referencia/auditoria.md` (enforced by `tests/unit/test_docs.py`).

## i18n

- Wrap visible strings with `_()` / `ngettext` / `_l` (lazy, for module-level constants) from `storageweb.i18n`; Jinja uses the newstyle i18n extension (`_("…", name=x)`).
- JS strings must be registered in `web/js_messages.py` and used via `t()` in the static JS.
- After adding strings: `tools/i18n.py update`, then fill the Spanish `msgstr` in `locale/es/LC_MESSAGES/messages.po` (compiled in memory, no `.mo`). Reusing an existing msgid reuses its translation (e.g. "Disabled" → "Deshabilitado").
- Web locale order: user preference > session > `Accept-Language` > `default_locale` (default `en`). CLI: `STORAGEWEB_LANG`/`LC_*`/`LANG`.

## Templates and tests: gotchas

- Macros imported with `{% from … import … %}` need `with context` to see `csrf_token`, `request` and context-processor variables.
- Never `{% set _ = … %}` in templates: it shadows gettext.
- Tests force Spanish (`tests/conftest.py`: autouse `spanish_locale`, config `"default_locale": "es"`), so assertions use Spanish text. Fixtures: `app`/`make_app(overrides)`, `client`, `logged` and `admin` (both return `(client, csrf_token)` and share the same `client` — use `app.test_client()` for a second session), `db_conn` for unit tests, `token_endpoint`/`entra_app` for SSO. Helpers in `tests/helpers.py` (`add_user`, `login`, `get_csrf`, `visible()` — strips the JS i18n catalog before negative text assertions).

## Current state

The admin has three trial views each for users (list/panels/cards) and groups (list/panels/access matrix), switchable in the UI; the user still has to pick one per area, after which the others should be removed.

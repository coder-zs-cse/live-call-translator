---
name: clean-architecture-patterns
description: Checklist and pattern library for producing production-grade, maintainable code across Python/FastAPI, C#/.NET, and JS/TS/Node. Use when starting a new project or feature, adding an API endpoint, choosing a design pattern (Strategy, Repository, DAO, Observer, Factory Method, Chain of Responsibility, Builder), reviewing/refactoring for layering violations, enforcing REST conventions, or flagging magic strings/`any` types.
---

# Clean Architecture & Design Patterns

A checklist and pattern library for producing production-grade, maintainable
code — for new projects, new features, or a review pass over existing code.
Applies across Python/FastAPI, C#/.NET, and JS/TS/Node.

**Golden rule first:** patterns are a means, not a scorecard. Never bolt on
a pattern the code doesn't need — a single hardcoded discount calculation
does not need a Strategy interface, and a project with one data source does
not need a repository abstraction "just in case." Before applying anything
below, name out loud (in a one-line comment or PR note) which problem the
pattern is solving here — variability, testability, decoupling,
extensibility. If there's no good answer, skip the pattern and write the
plain, boring code. Over-engineering is the same sin as under-engineering:
both trade real clarity for imagined future flexibility. When in doubt,
prefer the simplest thing that satisfies Single Responsibility and is easy
to test — patterns get introduced when a second variant, a second data
source, or a second consumer actually shows up (rule of three), not
preemptively.

## 1. Layering & separation of concerns (applies to every API/service)

Enforce this layering strictly — no business logic in controllers, no HTTP
concerns in services, no query logic outside the data-access layer:

- **Controller / Router layer** — parses and validates the request (or
  delegates validation to a schema/DTO), calls exactly one service method,
  maps the result/exception to an HTTP response. No business rules, no
  direct DB or external-API calls here, ever.
- **Service layer** — owns business logic and orchestration: combines
  calls to one or more repositories/DAOs/external clients, enforces
  business rules, raises domain-specific exceptions. Framework-agnostic
  where possible (no Request/Response objects leaking in).
- **Repository / DAO layer** — owns persistence only: CRUD and queries
  against one aggregate/table, hidden behind an interface so the service
  layer depends on an abstraction, not a specific DB driver or ORM.
  Repository pattern for aggregate-oriented persistence ("give me a
  User"), DAO pattern when you want a thinner, table-shaped wrapper
  ("give me rows from users_table") — pick one convention per project and
  stay consistent.
- **Domain/model layer** — plain data structures and enums/constants; no
  I/O.

When reviewing or writing a feature, ask: could I swap the database, or
unit-test the service with a fake repository, without touching the other
layers? If not, the layers have leaked into each other — fix that before
adding more code.

## 2. REST API conventions

- Endpoints are resource nouns, not verbs: `POST /orders`,
  `GET /orders/{id}`, `GET /orders?status=pending`, not `/createOrder` or
  `/getOrderById`.
- Use plural nouns, nested resources for real ownership only
  (`/users/{id}/orders`, not `/getUserOrders`), and correct HTTP
  verbs/status codes (201 on create, 204 on delete, 404 vs 400 vs 422 used
  correctly, not everything as 200/500).
- Version the API (`/v1/...` or a header) once it has external consumers.
- Request/response shapes go through explicit DTOs/schemas (Pydantic
  models, C# DTOs, TS interfaces/zod schemas) — never pass raw dicts/`any`
  across a layer boundary.
- Pagination, filtering, and sorting follow one consistent query-param
  convention across the whole API, not ad hoc per endpoint.

## 3. Pattern library — what each one is for, so it's applied on purpose

- **Strategy** — interchangeable algorithms behind one interface (e.g.
  pricing rules, notification channels, ranking/scoring logic). Reach for
  it when an if/elif/switch on a "type" field is picking behavior and a
  new type is likely to be added later.
- **Repository** — abstracts persistence for an aggregate so the service
  layer never imports an ORM/DB driver directly. Enables swapping storage
  and mocking in tests.
- **DAO (Data Access Object)** — thin, table/collection-shaped data
  access, one per table/collection, no business logic. Use when you want
  persistence mapping to be dumber and more literal than a Repository's
  aggregate view.
- **Observer** — decouples an event from its side effects (e.g. "order
  placed" triggers logging, email, analytics, cache invalidation — each
  as an independent subscriber). This is the default pattern for
  logging/telemetry hooks and audit trails: emit an event, don't hardcode
  every side effect inline in the service method.
- **Factory Method** — centralizes object creation when construction
  logic varies by type/config (e.g. building the right LLM client, the
  right queue consumer, the right parser for a file type). Keeps
  `if type == X: return XImpl()` branching in exactly one place instead
  of scattered across call sites.
- **Chain of Responsibility** — a pipeline of handlers where each either
  processes a request/message or passes it on (middleware, validation
  pipelines, request preprocessing, multi-stage moderation/
  classification). Use it when the number/order of steps is expected to
  change.
- **Builder** — for constructing complex objects/configs step by step
  (multi-field request payloads, complex query objects, test fixtures
  with many optional fields) instead of telescoping constructors or giant
  kwargs dicts.
- **Single Responsibility** — the umbrella rule: a class/module/function
  should have exactly one reason to change. If describing what a file
  does needs "and", it's a signal to split it.

## 4. Coding habits to enforce everywhere

- **No magic strings/numbers.** Any string/number used for comparison,
  branching, or repeated more than once becomes a named constant or an
  enum (Python `enum.Enum`/`StrEnum`, TS enum/union of string literals,
  C# enum). This includes status strings, event names, config keys, and
  error codes.
- **No `any` / untyped escape hatches.** Define an interface, TypedDict,
  Pydantic model, protocol, or C# interface for every non-trivial data
  shape crossing a function or layer boundary. In TS, prefer `unknown` +
  narrowing over `any` when the shape is genuinely unknown. In Python,
  type-hint everything public and run mypy/pyright in strict-ish mode
  where feasible.
- **Depend on interfaces, not concrete classes, at layer boundaries**
  (service depends on `IOrderRepository`, not `PostgresOrderRepository`)
  — this is what makes Strategy/Factory/Repository actually swappable and
  testable, not just theoretically so.
- **Fail loudly and specifically** — custom/domain exceptions instead of
  generic ones, no silent `except: pass`.
- **One export per concern** — avoid "god files" (`utils.py`,
  `helpers.js` with 40 unrelated functions); group by domain/feature, not
  by technical layer alone, when the project grows past a handful of
  files.

## 5. Clean directory structure (pick the one matching the stack, adapt names)

**Python/FastAPI:**

```
app/
  api/            # routers/controllers, one file per resource
  services/       # business logic, one file per domain concern
  repositories/    # persistence interfaces + implementations
  models/         # ORM models
  schemas/        # Pydantic request/response DTOs
  core/           # config, constants, enums, exceptions, logging setup
  dependencies.py  # DI wiring (interfaces -> concrete impls)
tests/
  unit/
  integration/
```

**Node/TypeScript:**

```
src/
  controllers/
  services/
  repositories/
  models/ (or entities/)
  dto/            # request/response interfaces
  constants/       # enums, constant maps
  middleware/      # chain-of-responsibility style pipeline
  config/
tests/
```

**C#/.NET:**

```
Solution/
  Api/            # Controllers
  Application/     # Services, interfaces
  Domain/         # Entities, enums, domain exceptions
  Infrastructure/  # Repository implementations, external clients
  Tests/
```

Adapt names to the project's existing conventions rather than forcing a
rename — consistency with what's already there beats matching this
template exactly.

## 6. How to apply this skill

- **New project:** propose the directory skeleton and layering above
  before writing feature code; confirm the DB/framework choice first
  since it shapes the repository/DAO layer.
- **New feature in an existing project:** follow the project's existing
  layering and naming even if it differs from the templates here — this
  skill's job is consistency and pattern discipline, not forcing a
  rewrite.
- **Refactor/review pass:** walk the checklist in order (layering → REST
  conventions → patterns actually needed → magic strings/`any` →
  directory fit) and call out violations with a one-line reason, not just
  "apply pattern X" — state why a pattern fits before introducing it, and
  flag plainly when a suggestion goes beyond a boring, well-understood
  alternative.
- **Always name the trade-off:** every pattern here adds a layer of
  indirection. State what it buys (testability, swappability, decoupling)
  and what it costs (more files, more indirection to trace through) so
  the choice is a real judgment call, not a reflex.

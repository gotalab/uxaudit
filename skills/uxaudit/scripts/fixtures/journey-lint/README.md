# Journey-script lint fixtures

Hand-rolled journey JSONs that exercise `validate_journey_scripts.mjs`'s
**static lint** layer (the part that runs before Playwright is started).
Each fixture carries a `_lint_expectation` block that documents what the
validator should produce — the field is ignored by the validator itself
(JSON `additionalProperties: true`).

## What is covered

| Fixture | What it tests |
|---|---|
| `should-fail-nanoid.json` | 21-char nanoid in `a[href='/recipe/<id>']` → `hardcoded-dynamic-id` |
| `should-fail-uuid.json` | UUID v4 in `[data-recipe-id='...']` → `hardcoded-dynamic-id` |
| `should-pass-flexible-href.json` | `a[href^='/recipe/']:not(...)` flexible match → no lint issue |
| `should-pass-kebab-slug.json` | Kebab-case slugs (`meal-dinner`, `slow-cooker-beef-stew-...`) → no lint issue |
| `should-pass-text-selector.json` | `text=` selector with long content → exempt from the dynamic-id rule |

## Running the fixtures

There are two ways to verify the validator's behavior against these:

### 1. Run the validator on a copy of just the failure cases

The `should-fail-*.json` files short-circuit at static lint, so Playwright is
never started. Safe to run anywhere:

```bash
mkdir -p /tmp/lint-fail-cases
cp scripts/fixtures/journey-lint/should-fail-*.json /tmp/lint-fail-cases/
node scripts/validate_journey_scripts.mjs /tmp/lint-fail-cases
```

Expected output:
```
[validate] dry-running 2 journey script(s) in /tmp/lint-fail-cases
[validate] should-fail-nanoid … FAIL @ step 1
[validate] should-fail-uuid … FAIL @ step 0
[validate] done — 0 ok / 2 fail (of 2)
```

Both `<name>.validation.json` files will have `ok: false`,
`static_lint_only: true`, and a `lint_kind: "hardcoded-dynamic-id"` step.

### 2. Verify the `should-pass-*` cases don't get flagged

These pass static lint and would then try to drive Playwright against
`http://localhost:3000`, so to verify them in isolation, point a real local
server at port 3000 first or test the lint logic via the unit test harness in
`test_journey_lint.mjs` (when added).

## Adding new lint rules

When you add a new rule to `staticLint()` in
`scripts/validate_journey_scripts.mjs`, also add at least one fail fixture
and one pass fixture here so the rule is regression-tested.

# uxaudit

[English](./README.md) | [日本語](./README_ja.md)

> Release-time UX checks for web apps. Replays your product's key user journeys, judges each one from screenshots alone, and gives you one report to triage.

> [!WARNING]
> **v2 alpha.** This branch replaces the v1 multi-agent pipeline with a small CLI. Interfaces may still change.

E2E tests tell you a flow runs. uxaudit asks what they don't: can a first-time user tell what the screen is for, pick the next action, finish the task, and recover from a mistake? It looks at the things teams forget to recheck before each release: first use, error recovery, feedback after an action, empty and real data, and the phone layout.

## How it works

1. **Journeys live in your repo.** `.uxaudit/journeys.yaml` lists 3–5 journeys in plain steps (`click: Save`, `fill: { target: { label: Email }, value: … }`). An agent drafts it once; you edit it. It becomes your release checklist, and every run measures the same thing.
2. **Capture is deterministic.** `uxaudit run` replays each journey with Playwright, records an annotated video (step caption, outlined target, cursor and click), and saves a screenshot after every step (with extra frames right after each action, so a toast that vanishes in half a second is still caught), plus machine signals: console errors, HTTP errors, slow steps, horizontal scroll, and clicks that changed nothing. Seconds per journey.
3. **The judge sees only pixels.** Each journey goes to a judge with no access to your code or the script, so it can't explain problems away. It writes pass/fail and at most five findings, each tied to a screenshot, a stage (understand / decide / act / recover) and a concrete fix.
4. **One report, triaged by people.** `uxaudit report` writes a single HTML page with the screenshots and a recording of each journey; every step and finding jumps to its moment in the video. Reviewers mark each finding **Fix**, **Accept** or **Not an issue**. Published as a Claude artifact, decisions are stored in the page and Claude reads them back; anywhere else, export `triage.json` and commit it. Decisions carry over to later runs.
5. **Fixes go back to the agent.** `uxaudit fixes` prints the findings to fix as Markdown for your coding agent.

### Sign-in and test data

```yaml
setup:
  command: npm run db:reset              # once per run
auth:
  member:                                # signed in once, reused by journeys
    steps:
      - goto: /login
      - fill: { target: { label: Email }, value: qa@example.com }
      - fill: { target: { label: Password }, value: "${env:QA_PASSWORD}" }
      - click: { role: button, name: Sign in }
journeys:
  - id: first-project
    auth: member
    before: npm run db:seed -- empty     # this journey's data
    ...
```

For Google and other third-party sign-in (also passkeys, 2FA, magic links), sign in by hand once and reuse the session:

```yaml
auth:
  member:
    recorded: true
    check: [{ goto: / }, { see: My projects }]   # proves the session still works
```

```bash
uxaudit auth record member   # opens a browser; sign in, then press Enter
```

The session is saved to `.uxaudit/.auth/` (git-ignored, owner-only) and each run checks it first, asking you to re-record when it expires. uxaudit never scripts the provider's own pages. For CI, use your auth vendor's test mode; to judge the sign-in flow itself (cancelled consent, account linking), run a local mock OIDC provider.

Secrets come from the environment or a git-ignored `.uxaudit/.env`, and stay as `${env:…}` in captions, briefs and reports. Sessions are kept in a temp directory and deleted after the run.

## Use it in Claude Code

```bash
/plugin marketplace add gotalab/uxaudit
/plugin install uxaudit@gotalab-uxaudit
```

Then ask Claude to "run uxaudit" or invoke `/uxaudit:uxaudit`. The first run installs Playwright and Chromium into the plugin's data directory.

## Use the CLI anywhere

The CLI is one file with Playwright as its only runtime dependency, so it runs the same way in cloud sessions, CI, and other coding agents (Codex, Cursor, Devin). Any agent that can read images can act as the judge: `uxaudit brief` prints a self-contained prompt.

```bash
uxaudit init                      # create .uxaudit/journeys.yaml
uxaudit run                       # capture every journey
uxaudit brief --journey <id>      # judge prompt → writes runs/<id>/verdicts/<journey>.json
uxaudit validate                  # check the verdict files
uxaudit report --artifact         # report.html (+ artifact version)
uxaudit triage import <file|dir>  # merge reviewer decisions into .uxaudit/triage.json
uxaudit fixes                     # Markdown fix list for a coding agent
```

Until the npm package is published, run it from a checkout: `pnpm install && pnpm build && node dist/uxaudit.mjs`, with Chromium from `npx playwright install chromium`.

## Try the demo

```bash
pnpm install && pnpm build
node examples/demo-app/serve.mjs &
cd examples/demo-app && DEMO_PASSWORD=pantry-demo node ../../dist/uxaudit.mjs run
```

The demo app (with sign-in and seeded data) hides six problems: a silent validation failure, a save confirmation that vanishes in 0.4s, a blank first screen, a header overflowing on phones, clipped long titles, and a failed sign-in with no message. The judge should find all six.

## Development

```bash
pnpm test         # build + unit tests
pnpm typecheck
```

`dist/uxaudit.mjs` is committed so the plugin works without a build step. Rebuild before committing source changes.

## License

Apache-2.0

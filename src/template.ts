export const TEMPLATE = `# uxaudit journeys — the UX checks you want to pass before every release.
# Keep each journey to what a first-time user would actually do.
# Docs: https://github.com/gotalab/uxaudit
version: 1
app:
  name: My App
  url: http://localhost:3000
  viewport: desktop      # mobile-sm | mobile | tablet | desktop | desktop-lg | WIDTHxHEIGHT
  lang: en               # report + judge language: en | ja

# Optional: run once before any journey, from the project root.
# setup:
#   command: npm run db:reset

# Optional: named sign-in flows. Secrets come from the environment or
# .uxaudit/.env (git-ignored) as \${env:NAME}; they never appear in reports.
# auth:
#   member:
#     steps:
#       - goto: /login
#       - fill: { target: { label: Email }, value: \${env:UXAUDIT_EMAIL} }
#       - fill: { target: { label: Password }, value: \${env:UXAUDIT_PASSWORD} }
#       - click: { role: button, name: Sign in }
#   google-user:              # Google/OAuth, passkeys, 2FA: sign in by hand once
#     recorded: true          # with: uxaudit auth record google-user
#     check:
#       - goto: /
#       - see: My projects    # text only a signed-in user sees

journeys:
  # focus: first-value | recovery | feedback | data | other
  - id: first-value
    title: A new user reaches first value
    focus: first-value
    # auth: member               # start signed in
    # before: npm run db:seed -- empty   # set up this journey's data
    goal: Someone who has never seen the app understands it and completes the core task.
    expect:
      - The first screen says what the app is for
      - The user can tell the task succeeded
    steps:
      - goto: /
      - click: Get started            # button/link name, label, placeholder or text
      # - fill: { target: { label: Email }, value: test@example.com }
      # - click: { role: button, name: Save }
      # - see: Saved                  # waits until this text is visible
`;

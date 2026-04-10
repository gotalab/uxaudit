# UX Layers — what we measure and what we don't

UX is a vague word. Before measuring it, we need to be precise about what part we're measuring.

## Three layers

```
┌─────────────────────────────────────┐
│ Retention                           │  ✗ Not measurable in a session
│ Will users come back tomorrow?      │     Needs real user logs over time
├─────────────────────────────────────┤
│ Desirability                        │  △ Partially measurable
│ Does it feel intentionally crafted? │     Heuristics + LLM judgment
├─────────────────────────────────────┤
│ Usability                           │  ◎ Measurable in a session
│ Can a user complete their goal?     │     Nielsen heuristics, pixel-only journeys
└─────────────────────────────────────┘
```

A note on naming: this conceptual page still uses the older Usability / Desirability / Retention vocabulary because that's the right shape for the rationale. The check catalog itself uses the dashboard-facing `band` (`ux` | `ui-risk`) and `subtype` (`understand` | `decide` | `act` | `recover`) axes, which are the only classification fields the validator and dashboard consume.

## What uxaudit covers

### Usability — fully covered

Operational checks. Can a user, given only the goal, complete the task?

- **Nielsen's 10 heuristics** — visibility of system status, match with the real world, user control, consistency, error prevention, recognition over recall, flexibility, minimalist design, error recovery, help.
- **Empty states** — does the app guide the user when there's no data?
- **Error recovery** — when something goes wrong, can the user get back on track?
- **Discoverability** — can a user find the features that exist?

These are detectable via pixel-only journey evaluation (operating the app from visible state only, one step at a time) or DOM inspection where the check is deterministic.

### Desirability — partially covered

Aesthetic and craft signals. We can detect the absence of craft (AI slop) and signs of intentional design, but we cannot measure subjective satisfaction in a single session.

- **AI slop patterns** — purple-blue gradients, generic card shadows, lorem ipsum, "coming soon" labels, hardcoded mock data
- **Visual hierarchy** — does the eye get guided to what matters?
- **Design Intent** — does it look like a deliberate product or a template?

What we **cannot** measure here:
- Whether it's actually fun to use
- Whether the user feels delight
- Whether the brand feels right for the audience

These require real users and time.

### Retention — not covered

This requires:
- Real users
- Multiple sessions over days/weeks
- Behavioral logs (DAU/MAU, session time, churn rate)

uxaudit deliberately stays out of this layer. **Don't try to predict retention from a single session.** It's the wrong tool for the job.

## Implication for the harness

A passing uxaudit score is **necessary but not sufficient**. It says:

> "This product passes the bar for someone to actually try it. Whether they want to keep using it is a question for real users."

The role of uxaudit in an autonomous build pipeline:

1. **Correctness verification** (unit / property-based / integration / E2E) → "does it work?"
2. **UI-risk verification** (visual regression / accessibility / responsive checks) → "did obvious UI or interaction failures slip through?"
3. **Experience verification** (uxaudit) → "is it understandable, usable, and intentional?"
4. **Real user judgment** (humans) → "is it valuable? do people return?"

The first three can be automated. The fourth cannot — and trying to automate it is the wrong target.

## Why these layers matter

If we don't separate the layers, two failure modes appear:

1. **Over-claiming**: scoring "good UX" from a script and assuming it means people will love the product
2. **Under-investing**: skipping usability checks because "we can't measure UX anyway"

By stating exactly what each layer measures and what it doesn't, uxaudit lets you invest the right amount in the right place.

# Sources for uxaudit

## The rule

Every check that involves a judgment call cites a published, publicly-verifiable
source. The rule isn't "cite everything." It's **don't invent criteria.**

An earlier draft of this skill made up rules from "general knowledge" and
cited an impossible arXiv paper alongside legitimate research. That was itself
a form of AI slop. This rewrite anchors any check that involves taste or
research in one of: NN/g, WCAG, ISO, canonical UX literature (Krug, Norman,
Cooper, Christensen), or peer-reviewed empirical studies.

**Self-evident anti-patterns don't need citations.** Lorem ipsum in production,
"Coming soon" badges, placeholder "John Doe" data. These ship as ai-slop
fingerprints without academic anchors because they are not judgment calls.
They are stub tells.

**What we explicitly do not accept as sources**, even when interesting or
widely shared:

- **Proprietary / internal guidance** (AI vendor skills, internal style guides).
  If a reader can't verify it without a specific plugin or account, it's not
  a publicly-verifiable source.
- **Tweets and social posts.** URLs can disappear; tweets are individual
  opinions, not research.
- **Single-author blog posts without peer review.** These may inform the
  rationale in prose, but not the `source` field.
- **Popular frameworks without empirical grounding** (e.g., growth-hacking
  heuristics).
- **Design-system opinions repeating the same principle.** Material, Apple HIG
  non-icon sections, IBM Carbon all say the same thing about consistency.
  Citing all of them is redundancy, not triangulation. Cite the underlying
  Nielsen heuristic or ISO standard and mention design systems in prose if
  relevant.

---

## A. Nielsen Norman Group (NN/g)

NN/g is the primary anchor for usability heuristics and empirical UX research.

### A.1 AI Prototyping in Real Design Contexts

URL: https://www.nngroup.com/articles/ai-prototyping/

NN/g tested Bolt, Claude, Figma Make, v0, Stitch, UX Pilot, Lovable, and
Replit and documented the slop signature across all of them:

- "All outputs share a similar, generic look: sans-serif typeface, minimalist
  styling, flat and interchangeable appearance."
- AI tools "default to Shadcn components and Tailwind CSS because those
  dominate their training data," producing homogenization across products.
- Documented defects: "poor visual hierarchy and element grouping, inadequate
  color contrast, inconsistent spacing and margins, no distinctive visual
  language."
- Framing: AI prototypes are "good from afar, but far from good."

**The empirical anchor for the entire `ai-slop/` category.** Used by
`ai-slop/purple-gradient`, `ai-slop/default-tailwind-palette`,
`ai-slop/generic-card-shadow`, `ai-slop/generic-font-stack`,
`ai-slop/rote-dark-toggle`, `ai-slop/shadcn-signature`,
`ai-slop/stock-illustration-hotlinks`, `desirability/visual-craft`.

### A.2 Nielsen's 10 Usability Heuristics

URL: https://www.nngroup.com/articles/ten-usability-heuristics/

Derived in 1994 from a factor analysis of 249 usability problems, refreshed
2020. The heuristics we cite directly:

| Heuristic | Check |
|---|---|
| #1 Visibility of system status | `usability/system-status-visibility`, `core-experience/primary-journey` |
| #2 Match between system and real world | `usability/vague-button-labels` |
| #3 User control and freedom | `core-experience/primary-journey` |
| #4 Consistency and standards | `usability/feature-consistency`, `usability/vague-button-labels` |
| #5 Error prevention | `core-experience/primary-journey` |
| #10 Help and documentation | `usability/empty-state-guidance` |

### A.3 Severity Rating Scale (0 to 4)

URL: https://www.nngroup.com/articles/how-to-rate-the-severity-of-usability-problems/

Nielsen's canonical severity scale defines the semantics of our `severity`
enum. Cosmetic maps to `minor`, major maps to `major`, catastrophe maps to
`critical`.

### A.4 First Impressions form in 50ms

URL: https://www.nngroup.com/articles/first-impressions-human-automaticity/

NN/g's summary of Lindgaard et al. 2006. Aesthetic judgment forms in 50ms
and is stable under longer exposure. NN/g's companion recommendation: max
approximately 4 accent colors, max 2 fonts. Used by
`ai-slop/generic-font-stack`, `usability/visual-hierarchy`,
`desirability/aesthetic-first-impression`.

### A.5 Empty State UX Best Practices (Pernice 2019)

URL: https://www.nngroup.com/articles/empty-state-interface-design/

Three rules for empty states: communicate system status, provide learning
cues, provide direct pathways. Used by `usability/empty-state-guidance`.

### A.6 Icon Usability

URL: https://www.nngroup.com/articles/icon-usability/

Icons must be consistent and recognizable across contexts. Decorative icons
add visual noise without communicative value. Used by `ai-slop/emoji-as-icon`,
`ai-slop/sparkle-ai-combo`, `ai-slop/emoji-feel`.

### A.7 Other NN/g articles cited as primary anchors

Each of the following is the primary NN/g anchor for a single check. All
articles are on nngroup.com; URLs are verifiable by searching the article
title on the site.

| Article | Check |
|---|---|
| Microcontent: How to Write Headlines, Page Titles, and Subject Lines (Nielsen 1998) | `ai-slop/default-tagline`, `ai-slop/hero-button-cliche`, `ai-slop/marketing-buzzwords`, `desirability/copy-craft` |
| Response Times: The 3 Important Limits (Nielsen 1993) | `usability/system-status-visibility` |
| Homepage Usability: 50 Websites Deconstructed (Nielsen 2001) | `core-experience/value-prop-clarity` |
| First Use vs Returning Use (Pernice 2019) | `usability/first-time-user-experience` |
| Task Success Rate | `core-experience/primary-journey` |

### A.8 `/rams` slash command (WCAG severity mapping)

Path: `~/.claude/commands/rams.md`

A curated WCAG 2.1 design-engineer checklist with Critical / Serious /
Moderate tiers. Used by `accessibility/focus-removed` (Serious, 2.4.7) and
`accessibility/heading-skip-levels` (Moderate, 1.3.1).

---

## B. W3C WCAG 2.2

URL: https://www.w3.org/TR/WCAG22/
Understanding documents: https://www.w3.org/WAI/WCAG22/Understanding/

axe-core covers the bulk of WCAG 2.2 automatically; targeted L1 checks add
things it misses or under-weights.

| Check | WCAG SC | Level |
|---|---|---|
| `accessibility/axe-core` | composite (1.1.1 / 1.4.3 / 2.4.4 / 4.1.2 / etc.) | A/AA |
| `accessibility/focus-removed` | 2.4.7 Focus Visible | AA |
| `accessibility/heading-skip-levels` | 1.3.1 Info and Relationships, 2.4.6 Headings and Labels | A / AA |
| `accessibility/font-hierarchy` | 1.4.4 Resize Text + 2.4.6 Headings and Labels | AA |

---

## C. ISO Standards

### C.1 ISO 9241-11:2018 (Usability: Definitions and Concepts)

URL: https://www.iso.org/standard/63500.html

Definition of usability (§3.1.1):

> The extent to which a system, product or service can be used by specified
> users to achieve specified goals with effectiveness, efficiency and
> satisfaction in a specified context of use.

The 2018 edition broadened "satisfaction" to include emotional and subjective
aspects. It also frames usability as an **outcome of interaction**, not a
property of a product.

This skill approximates **effectiveness** (does the page show real content?
are the controls labeled?) and **efficiency** (is the hierarchy scannable?).
Used by `ai-slop/lorem-ipsum-data`, `ai-slop/placeholder-names`,
`core-experience/primary-journey`.

### C.2 ISO 9241-110:2020 (Interaction Principles)

URL: https://www.iso.org/standard/75258.html

Seven interaction principles. The ones used here:

- **Self-descriptiveness**: `usability/vague-button-labels`
- **Conformity with user expectations**: `usability/feature-consistency`
- **Suitability for learning**: `usability/first-time-user-experience`

---

## D. Canonical UX literature

### D.1 Steve Krug: *Don't Make Me Think* (3rd ed., 2014)

ISBN 978-0321965516. The three laws of usability:

1. Don't make me think (pages should be self-evident)
2. It doesn't matter how many clicks as long as each is mindless
3. Get rid of half the words, then get rid of half of what's left

Used by: `accessibility/font-hierarchy` (Ch 3 "Billboard Design 101"),
`ai-slop/coming-soon-text` (Law #3), `ai-slop/cta-trailing-emoji` (Law #2),
`ai-slop/default-tagline` (Law #3), `ai-slop/emoji-as-icon` (Law #3),
`ai-slop/hero-button-cliche` (Law #3), `ai-slop/marketing-buzzwords` (Law #3),
`core-experience/value-prop-clarity` (Ch 6 "Street signs and breadcrumbs"),
`desirability/copy-craft` (Ch 5 "Omit needless words"),
`usability/excise-detection` (Law #3), `usability/vague-button-labels` (Law #1),
`usability/visual-hierarchy` (Ch 3).

### D.2 Alan Cooper: *About Face* (4th ed., 2014)

ISBN 978-1118766576. Ch 11 "Eliminating Excise" is the canonical treatment of
work the user must do that does not directly serve their goal. Cooper defines
excise as "all the activities that don't contribute to the user's goals: they
exist only because the system exists." Primary anchor for
`usability/excise-detection`.

### D.3 Don Norman: *Emotional Design* (2004)

ISBN 978-0465051366. Three layers of emotional response: visceral (immediate
aesthetic), behavioral (it works), reflective (it makes me feel something).
Most LLM-generated UIs achieve only the behavioral layer. Used by
`desirability/delight-moments`.

### D.4 Aarron Walter: *Designing for Emotion* (A Book Apart, 2011)

Argues that delightful micro-moments are what convert users into advocates.
Used by `desirability/delight-moments`.

### D.5 Clayton Christensen: Jobs To Be Done

Christensen's framework frames products as being "hired" by users to complete
a specific job in a specific situational, functional, and emotional context.
The classic example is Christensen's milkshake study: users "hired" fast-food
milkshakes as solo commute-time fillers, a job no taste-test survey could have
surfaced because the situational context was invisible to surface research.

JTBD is the source of UX thinking about situational and contextual
understanding. The same feature can serve or fail depending on what job the
user is trying to complete, and that job is often not what surface language
suggests. Used by `core-experience/primary-journey` (what is the user hiring
this app to do?) and `core-experience/value-prop-clarity` (can a first-time
visitor tell what job this app does?).

Key reference: Christensen, Hall, Dillon, Duncan (2016), *Competing Against
Luck: The Story of Innovation and Customer Choice*.

---

## E. Peer-reviewed empirical studies

### E.1 Lindgaard et al. 2006

*Attention web designers: You have 50 milliseconds to make a good first
impression!* Behaviour & Information Technology 25(2), 115 to 126.

Empirical finding: users form aesthetic judgments of a website in 50ms, faster
than conscious thought. Those judgments persist as overall quality assessments
(the aesthetic-usability effect, later popularized by Don Norman in *Emotional
Design*). Used by `desirability/aesthetic-first-impression`.

---

## F. Platform UI guidance (narrow use only)

### F.1 Apple Human Interface Guidelines (Icons)

URL: https://developer.apple.com/design/human-interface-guidelines/sf-symbols

Apple HIG is unambiguous that UI controls should use SF Symbols, not emoji,
because emoji cannot be color-controlled, cannot scale crisply, and render
differently across platforms. Used narrowly by `ai-slop/cta-trailing-emoji`
and `ai-slop/emoji-feel` as the primary "don't use emoji as UI chrome" anchor.
**This is the only platform UI guidance cited as a `source` field** in the
catalog. Other design systems (Material, IBM Carbon, Fluent) are not used as
source citations because they restate the same Nielsen / ISO principles; when
they matter to a check, they appear in the rationale prose.

---

## G. axe-core (Deque)

URL: https://github.com/dequelabs/axe-core
Rule descriptions: https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md
ACT implementation report: https://www.w3.org/WAI/standards-guidelines/act/implementations/axe-core/

Industry-standard automated accessibility testing engine. Every rule is tagged
to a specific WCAG SC and is conservatively tuned to avoid false positives.
Used by `accessibility/axe-core`.

---

## Closing note

A check that involves a judgment call and cannot be tied to one of the above
categories does not ship. Obvious anti-patterns can ship without an academic
anchor because they are not judgment calls. Every other check carries its
primary source in the `source` field of its `check.json`, and that field
stays inside the rules above.

If you are adding a check, read `references/authoring/check-authoring.md`
before editing. The pre-flight validator (`scripts/validate_checks.py`)
enforces the schema. It cannot enforce taste. That's what this document is
for.

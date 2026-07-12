# Telos design system

This document locks the tokens and rules for Telos's visual design, so the
app stops defaulting to generic "AI slop" patterns (Inter, purple-indigo
gradients, soft drop shadows, uniform three-up cards) and instead reads as a
deliberately designed study tool.

All values below are defined once in `src/App.jsx` (the app is a single
Vite/React file using inline styles + one shared `<style>{css}</style>`
block — there's no separate CSS/Tailwind config). Search for the constant
names to find every usage.

## Forbidden

- Inter, Roboto, Open Sans, or `system-ui` as a font-family fallback.
- Purple-to-indigo gradients.
- Soft, blurred drop shadows for elevation — use a 1-2px solid border
  instead. (The one exception: a 0-blur `outline`/inset ring used as a
  *state* indicator, e.g. the picked-radio dot, is not an elevation shadow
  and is fine.)
- The phrase "transform your workflow" or other generic SaaS copy.

## Typography

- **Display / headings**: `Fraunces`, weight 600. Used for h1/h2/h3-level
  section titles (`panelH`, `docTitle`, `podTitle`, `authTitle`) and a
  handful of large numeric displays (`scoreNum`, flashcard term). Telos is a
  dense app UI, not a marketing page, so "headings" here means every
  section-title-level element, not literally only `<h1>`/`<h2>` tags.
- **Body + UI controls**: `Source Sans 3`, 16px base, line-height 1.6 (set
  once on `styles.app`, inherited everywhere via `font-family: inherit`).
- **Numbers**: `fontVariantNumeric: "tabular-nums"` on scores, dates, usage
  counters — already applied throughout, kept consistent.
- Fallback stacks are `'Fraunces', Georgia, serif` and `'Source Sans 3',
  sans-serif` — a real serif/generic-keyword fallback, never `system-ui` or
  a third named typeface.

## Color tokens (`src/App.jsx`, just above the `styles` object)

| Token | Value | Use |
|---|---|---|
| `ink` | `#1c2522` | primary text |
| `paper` | `#f6f4ee` | page background |
| `moss` | `#3f7d5e` | primary accent — buttons, icons, borders, large display text |
| `mossDeep` | `#2e5d45` | darker moss for small text/labels where `moss` alone doesn't clear contrast |
| `amber` | `#e6a23c` | secondary accent — backgrounds, borders, decorative underlines only |
| `amberText` | `#8f5a0f` | **text-safe** amber for small labels/chips/kickers (`amber` itself fails WCAG AA as text) |
| `line` | `#e2ded3` | 1px hairline borders / section dividers |
| `muted` | `#5a6560` | secondary/muted text (darkened from the original `#6f7a73`, which failed AA at small sizes) |

**Rule going forward**: `moss` and `amber` are for icons, borders, large
display type (≥18.66px bold or ≥24px regular) and backgrounds only. Any
*small* text (labels, kickers, chip text, focus rings) uses `mossDeep` /
`amberText` instead. This is why the two pairs exist — don't collapse them
back into one variable.

## Accessibility (WCAG 2.2 AA)

- **Contrast**: every text/background pairing above was measured against
  the WCAG contrast formula and passes 4.5:1 (normal text) or 3:1 (large
  text / non-text UI). This is what drove the `muted`/`amberText` changes —
  the previous `#6f7a73` and raw `amber` both failed at the sizes they were
  used at (2.19:1 and 4.06:1 respectively).
- **Focus visibility**: every interactive element gets a 3px solid
  `amberText` outline on `:focus-visible` (`outline-offset: 2-3px`). Most
  controls had their own rule already; a global fallback (`button, a,
  input, [role="button"], [tabindex]`) now covers anything that doesn't.
- **Keyboard**: the upload dropzone (`role="button"`) now responds to
  Enter/Space, not just click — a `role="button"` div with no keydown
  handler is a keyboard trap.
- **Live regions**: error text uses `role="alert"`; in-progress states
  (uploading, regenerating, generating audio, checking session) use
  `role="status" aria-live="polite"` so screen reader users hear what
  changed instead of silence.
- **Labels**: inputs that only had a `placeholder` (email/password,
  tutor chat, focus-topic) now also carry `aria-label`, since a placeholder
  disappears once typed and isn't a reliable programmatic label.
- **Touch targets**: bumped `historyDelete`'s hit area to ≥24×24px (WCAG
  2.5.8). Everything else was already ≥24px.
- **Skip link**: `Skip to content` link (visually hidden until focused)
  added before the header, landing on `id="main-content"` on the page's
  `<main>`.
- **Reduced motion**: already respected globally (`prefers-reduced-motion:
  reduce` disables the flip/fade/spin animations) — unchanged, just noting
  it's covered.

## Layout / responsive

Telos is a single-page app (upload → tabbed study screen: Summary / Quiz /
Cards / Podcast / Tutor), not a marketing site, so there's no literal
12-column grid or hero-in-columns-2-8 to build. What's already in place and
kept:

- Content max-width `min(1200px, 100vw - 56px)`, centered.
- `@media (min-width: 900px)`: study screen becomes a two-column layout —
  a sticky tab sidebar (col 1) + panel (col 2) — the closest equivalent to
  an asymmetric desktop layout for this app's IA.
- `@media (max-width: 700px)` / `(max-width: 420px)`: single-column,
  full-bleed tabs, stacked hero.
- Section dividers are `1px solid ${line}` everywhere, never a shadow.

**Scoped out of this pass**: forcing every spacing value onto a literal
24px rhythm. Telos is a dense app (quiz options, chat bubbles, transcript
lines) where 6-14px micro-gaps are load-bearing for readability; collapsing
those to 24px multiples would hurt the UI it's meant to serve. The 8px base
grid is already true at the macro level (section margins, panel padding);
if you want strict 24px section rhythm audited line-by-line, that's a
follow-up, not part of this change.

## Student-centric direction

Not a new feature set — a tone/interaction principle for future work:

- Encouraging, specific copy over generic SaaS copy ("Here's where to
  focus" + named weak topics, not "Something went wrong, try again").
- Tactile, real interactions over decorative ones (the 3D flashcard flip
  with a deck-stack behind it is the model — do more of that, not less).
- Avoid uniform three-up card rows; asymmetric/staggered layouts read as
  more considered.
- **Not done here** (flagged as a follow-up, needs backend/state changes,
  not just styling): streaks, daily goals, XP — the `usageBadge` already
  shows `today/limit` and could be reframed as a goal instead of a quota
  warning, but that's a product decision, not a styling one.

## How to revert

All of the above landed in a single, isolated commit on
`claude/app-review-api-key-h0cr53`. To undo the whole pass:

```
git revert <commit-sha>
```

That's it — one command, nothing else touched. `git log --oneline -1` on
this branch shows the commit; `git show --stat <sha>` shows exactly what it
touched (this file + `src/App.jsx`, nothing else).

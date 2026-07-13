# Syrora design system

## Overview

Syrora is a single-learner study companion — upload a PDF, get a summary,
quiz, flashcards, podcast, and a tutor chat scoped to that document. The
design system exists to keep the app off the generic "AI slop" defaults
(Inter, purple-indigo gradients, soft drop shadows, uniform three-up cards)
and reading as a deliberately designed tool: warm paper background, a
serif/sans display pairing, moss-green accent, hard 1px borders instead of
elevation shadows.

All values below are defined once in `src/App.jsx` (the app is a single
Vite/React file using inline styles + one shared `<style>{css}</style>`
block — there's no separate CSS/Tailwind config). Search for the constant
or style-key names to find every usage.

---

## Colors

| Token | Value | Use |
|---|---|---|
| `ink` | `#1c2522` | Primary text |
| `paper` | `#f6f4ee` | Page background |
| `moss` | `#3f7d5e` | Primary accent — buttons, icons, borders, large display text |
| `mossDeep` | `#2e5d45` | Darker moss for small text/labels where `moss` alone doesn't clear contrast |
| `amber` | `#e6a23c` | Secondary accent — backgrounds, borders, decorative underlines only |
| `amberText` | `#8f5a0f` | **Text-safe** amber for small labels/chips/kickers (`amber` itself fails WCAG AA as text) |
| `line` | `#e2ded3` | 1px hairline borders / section dividers |
| `muted` | `#5a6560` | Secondary/muted text |
| Error | `#b03d2e` on `#fdeeea` bg, `#f2cfc5` border | Error messages, failed states |
| Weak-topic chip | `#fbeede` bg / `amberText` text / `#f0d9b8` border | Quiz "topics to review" |
| "Current" tag | `#dcebe2` bg / `mossDeep` text | Active regenerate-option indicator |
| Notice banner | `#fbeede` bg / `amberText` text / `#f0d9b8` border | Early Access banner — same tokens as the weak-topic chip, deliberately, so "notice" reads consistently |
| Modal scrim | `rgba(28, 37, 34, 0.45)` (`ink` at 45%) | Overlay behind a modal card |

**Rule**: `moss` and `amber` are for icons, borders, large display type
(≥18.66px bold or ≥24px regular) and backgrounds only. Any *small* text
(labels, kickers, chip text, focus rings) uses `mossDeep` / `amberText`
instead — every pairing above was checked against the WCAG contrast formula
and clears 4.5:1 (normal text) or 3:1 (large text / non-text UI). Don't
collapse the pairs back into one variable; the split is what keeps small
text legible.

## Typography

- **Display / headings**: `Fraunces`, weight 600. Used for section-title-
  level elements (`panelH`, `docTitle`, `podTitle`, `authTitle`) and large
  numeric displays (`scoreNum`, flashcard term) — Syrora is a dense app UI,
  not a marketing page, so "heading" means every section-title-level
  element, not literally only `<h1>`/`<h2>` tags.
- **Body + UI controls**: `Source Sans 3`, 16px base, line-height 1.6 (set
  once on `styles.app`, inherited everywhere via `font-family: inherit`).
- **Numbers**: `fontVariantNumeric: "tabular-nums"` on scores, dates, usage
  counters, trend counts.
- Fallback stacks: `'Fraunces', Georgia, serif` and `'Source Sans 3',
  sans-serif` — a real serif/generic-keyword fallback, never `system-ui` or
  a third named typeface.

| Style | Font | Size | Weight | Line height |
|---|---|---|---|---|
| Hero (`h1`) | Fraunces | `clamp(42px, 5vw, 78px)` | 600 | 1.02 |
| Document title (`docTitle`) | Fraunces | `clamp(30px, 3.6vw, 52px)` | 600 | 1.02 |
| Panel heading (`panelH`) | Fraunces | 20px | 600 | default |
| Podcast title (`podTitle`) | Fraunces | 21px | 600 | 1.15 |
| Body / sub (`sub`) | Source Sans 3 | `clamp(16px, 1.35vw, 20px)` | 400 | 1.6 |
| UI label / button | Source Sans 3 | 13.5–14.5px | 600 | default |
| Eyebrow / kicker | Source Sans 3 | 11–11.5px, uppercase, 0.12–0.16em tracking | 600 | default |
| Caption / meta | Source Sans 3 | 12–13px | 400–500 | default |

## Spacing

- **Base unit**: 8px, applied at the macro/section level (panel padding,
  section margins, header padding).
- **Not** a literal 24px rhythm on every value — Syrora is a dense UI (quiz
  options, chat bubbles, transcript lines) where 6–14px micro-gaps are
  load-bearing for readability. Forcing those to 24px multiples would hurt
  the UI it serves. If you want a strict macro-only audit, common values
  in use: `4 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 20 / 24 / 28 / 36 / 44 / 80`.
- **Content max-width**: `min(1200px, 100vw - 56px)`, centered.
- **Panel padding**: `clamp(24px, 3.2vw, 44px)`.
- **Card/list-row padding**: 10–16px.

## Border Radius

| Size | Value | Use |
|---|---|---|
| Small | 6–8px | Icon buttons, small chips, inline controls |
| Medium | 10–12px | Buttons, inputs, history rows |
| Large | 14–16px | Player card, upload icon tile |
| XL | 18px | Panels, auth form, flashcard face |
| Full | 20px / `50%` | Pill badges/chips, round buttons |

## Elevation — no soft shadows

Syrora does **not** use blurred drop shadows for elevation. Depth is
expressed with a 1–2px solid border (`line`, `moss`, or `amberText`
depending on context) instead. The one narrow exception: a 0-blur
`outline`/inset ring used as a *state* indicator (e.g. the picked quiz
option's dot) — that's not an elevation shadow, it's a hard-edged state
ring, and it's fine.

If you're tempted to add `box-shadow` for a "floating card" look: don't.
Use a border, or the flashcard pattern below (a real 3D transform +
stacked-behind pseudo-elements) if you need actual depth.

---

## Components

### Buttons

| Variant | Fill | Text | Border | Radius | Padding | Font |
|---|---|---|---|---|---|---|
| Primary (`primaryBtn`) | `moss` | `#fff` | none | 10px | `12px 20px` | 14.5px/600 |
| Send (`sendBtn`, `playBtn`) | `moss` | `#fff` | none | 10px / 50% | 46–48px square | icon-only |
| Outline accent (`audioBtn`, `focusGenBtn`) | `#fff` / `moss` | `mossDeep` / `#fff` | `1.5px solid moss` | 10px | `8-9px 15-16px` | 13.5px/600 |
| Ghost (`resetBtn`) | transparent | `muted` | `1px solid line` | 8px | `7px 12px` | 13px/400 |
| Underline link (`sampleBtn`) | transparent | `ink` | `1.5px solid amber` bottom only | — | — | 14px/500 |
| Selectable pill (`regenActionBtn`) | `#fff` (current: `#eef4f0`) | `mossDeep` | `1.5px solid line` (current: `moss`) | 10px | `9px 15px` | 13.5px/600 |
| Icon-only round (`fc-arrow`) | `#fff` | `mossDeep` | `1.5px solid line` | 50% | 40×40px | — |
| Third-party (`googleBtn`) | `#fff` | `ink` | `1px solid line` | 10px | `11px 20px` | 14.5px/600 |

- **Disabled**: `opacity: 0.5`, `cursor: default` — set inline per-button,
  not a shared class (search each button's `disabled` prop for the exact
  spot).
- **Focus**: every button gets a 3px solid `amberText` outline on
  `:focus-visible` (`outline-offset: 2px`), either from a component-
  specific rule or the global fallback (`button, a, input, [role="button"],
  [tabindex]`).
- **Loading**: spinner replaces the icon in-place, label text changes to a
  "…ing" verb ("Generating…", "Loading…") — never a separate disabled
  overlay. Spinners inside labelled buttons are `aria-hidden="true"`
  (the button's own text/label is what screen readers announce).
- **Third-party auth** (`googleBtn`, "Continue with Google"): the one place
  the design system intentionally steps aside — Google's own multi-color
  "G" glyph (`GoogleIcon`) keeps its real brand colors regardless of the
  moss/amber palette, per Google's sign-in button guidelines. Sits above
  the email/password form on the sign-in screen, separated by a plain
  `or` divider (`authDivider`/`authDividerLine`/`authDividerText`).

### Cards / panels

| Variant | Fill | Border | Radius | Padding | Use |
|---|---|---|---|---|---|
| Panel (`panel`) | `#fff` | `1px solid line` | 18px | `clamp(24px, 3.2vw, 44px)` | Main tab content container |
| Auth form (`authForm`) | `#fff` | `1px solid line` | 18px | `28px 24px` | Sign-in card |
| List row (`historyItem`) | `#fff` | `1px solid line` (hover: `moss`) | 12px | `10px 12px` | Recent-document row |
| Inset panel (`player`) | `paper` | `1px solid line` | 14px | `16px 18px` | Audio player |

No card in the app uses a shadow. Hover states move the border color to
`moss`, not add elevation.

### Inputs

| State | Border | Background | Notes |
|---|---|---|---|
| Default | `1px solid line` | `#fff` (auth) / `paper` (chat, focus-topic) | 10px radius, `9-12px` vertical padding |
| Focus | `outline: none` on the element itself; the browser/`:focus-visible` ring is intentionally suppressed only where a custom ring exists elsewhere — otherwise the global 3px `amberText` fallback applies | — | — |
| Error | n/a — errors render as a separate `role="alert"` message below the form, not a red input border | — | — |

- Every input that has only a `placeholder` also carries an `aria-label` —
  a placeholder disappears once typed and isn't a reliable programmatic
  label on its own.
- Font: `inherit` (Source Sans 3), 13.5–14.5px.

### Chips / badges

| Variant | Fill | Text | Border | Radius | Use |
|---|---|---|---|---|---|
| Doc chip (`docChip`) | `#fff` | `muted` | `1px solid line` | 20px (pill) | File name indicator |
| Usage badge (`usageBadge`) | `#fff` | `muted` | `1px solid line` | 20px (pill) | "3/10 today" quota |
| Trend badge (`trendBadge`) | `#fff` | `mossDeep` (up/flat) or `muted` (down) | `1px solid line` | 20px (pill) | "N sessions this week" — real data from `history`, never fabricated; hidden below 760px to avoid crowding the header |
| Weak-topic chip (`weakChip`) | `#fbeede` | `amberText` | `1px solid #f0d9b8` | 20px (pill) | Quiz review topics |
| Current-option tag (`regenCurrentTag`) | `#dcebe2` | `mossDeep` | none | 5px | "current" label inside a selected regenerate option |
| Method-style kicker (`podKicker`) | none | `amberText` | none | — | Uppercase eyebrow label, 11px |

**Trend badges never use a negative/red framing for "less activity."**
Studying less this week isn't a failure state — `trendBadge` uses `muted`
(neutral gray), not error red, when the delta is negative. This is a
direct extension of the student-centric principle below: the app should
never guilt a learner over their own data.

### Lists & navigation

- **Tabs** (`tabs`/`tab`): horizontal on mobile (scrollable, `border-bottom`
  underline style), switches to a sticky vertical sidebar at ≥900px.
  Active tab: `mossDeep` text, `moss` bottom border (or full border on
  desktop), 600 weight.
- **History list** (`historyList`/`historyItem`): 6px row gap, each row a
  bordered card (see Cards above), hover border → `moss`. The grid track is
  `minmax(0, 1fr)` so long nowrap titles ellipsize instead of widening the
  track. On the upload screen it renders in two containers with CSS deciding
  which is visible: inline below the dropzone (default), or a left sidebar at
  ≥1100px (`.history-sidebar`, 300px column, full-height `1px line`
  right divider, sticky scrollable body) — same Claude-style placement as the
  study screen's ≥900px tab sidebar. While the first fetch after sign-in is
  in flight, show a small spinner row ("Loading your documents…",
  `.spinner-sm`, 18px) instead of nothing; once resolved with no documents,
  the whole section — sidebar and inline — disappears entirely. Never show an
  empty "Recent documents" shell.
- **Quiz attempt history** (`quizHistory`/`attemptRow`): plain rows
  separated by `1px solid line` top border, expandable on click.

### Selectable options (quiz radios)

`.opt` / `.optDot` — a full-row selectable button styled like a radio, not
a native `<input type="radio">`:

- Rest: `paper` background, `1.5px solid line` border, 11px radius, 16×16
  circular dot with `2px solid line`.
- Hover: border → `moss`.
- Picked: row border/background → `moss`/`#f0f5f1`; dot fills `moss` with
  a hard-edged `outline: 3px solid #f0f5f1; outline-offset: -3px` ring
  (converted from a `box-shadow` — same look, no blur).
- Focus: 3px solid `amberText` outline, 2px offset.

### Flashcards

The signature tactile component — a real 3D flip via CSS `transform:
rotateY(180deg)` on `.fc-card`, with two pseudo-element "cards" behind it
(`::before`/`::after`, rotated ±1–2°) simulating a stacked deck. Front face
border `2px solid moss`; back face `2px solid amberText` on a `#fdf9f0`
tint. No shadow — depth comes from the transform + the deck-stack borders,
not elevation.

### Chat / transcript

- Message bubbles (`bubble`): tutor bubbles use `paper` fill + `line`
  border; user bubbles use `moss` fill + white text. Asymmetric corner
  radius (`borderBottomLeftRadius`/`borderBottomRightRadius: 4`) gives the
  speech-bubble tail effect without an actual tail shape.
- The scrolling message list is `role="log" aria-live="polite"` so new
  tutor replies are announced.

### Banners

- **Early Access banner** (`bannerBar`): the one banner in the product today.
  Amber-tint notice style — `#fbeede` fill, `#f0d9b8` border, `amberText`
  text — same palette as the weak-topic chip, so "notice" reads
  consistently everywhere it appears. 12px radius, sits directly under the
  header, `1200px`-max content width to match the header/panel measure.
  Dismissible (X button, right-aligned); dismissal is remembered in
  `localStorage` under a versioned key (`syrora_early_access_banner_dismissed_v1`)
  — bump the version suffix (or the key's name) when the message changes
  materially so a stale dismissal doesn't silently hide a genuinely new notice.

### Modals

- **Overlay** (`modalOverlay`): `position: fixed`, full viewport, `ink` at
  45% opacity (`rgba(28, 37, 34, 0.45)`) as the scrim — no blur. Click on
  the overlay (outside the card) closes; click inside the card does not
  (`stopPropagation`).
- **Card** (`modalCard`): `#fff` fill, `1px solid line` border, **18px**
  radius (Panel-tier, see Border Radius table), `28px 26px` padding, no
  shadow — same "depth via border, not blur" rule as everything else.
  Max width `440px`, scrolls internally past `100svh - 40px` tall.
  Entrance uses the existing `.fade` animation, nothing modal-specific.
- **Header row**: `panelH` title (Fraunces 20px/600) + a ghost icon-only
  close button (`modalClose`, `muted` color, no border, 18px `X` icon).
- **Focus/dismiss**: `Escape` closes (handled on the overlay's
  `onKeyDown`); the close button and every interactive element inside use
  the standard button/input specs above, so the global focus-visible
  fallback applies with no extra rules needed (this is also why
  `textarea:focus-visible` was added to that fallback selector — the
  feedback form's comment box is the first `<textarea>` in the app).
- **Current instance**: the feedback modal (rating + comment). Reuses
  `primaryBtn` for submit and `resultSub` for helper text — no new button
  variant was needed.

### Star rating

- Five icon-only buttons (`starBtn`, `Star` from lucide), no border/fill on
  the button itself — just the icon. Selected/hovered stars fill `amber`
  (icons are explicitly amber-safe per the Colors rule above, since the
  restriction is on *text*, not icon fills); unfilled stars are an outline
  in `line`. `role="radiogroup"` / `role="radio"` + `aria-checked`, since
  this is a single-choice control, not a checkbox group.

### Not yet in the product

Checkboxes, native radio inputs, and tooltips don't exist in Syrora today —
don't invent specs for components that aren't built. If one of these gets
added, extend this file with a real section following the same format
(state table + notes), not a guess.

---

## Accessibility (WCAG 2.2 AA)

- **Contrast**: every text/background pairing in the Colors table was
  measured against the WCAG contrast formula.
- **Focus visibility**: 3px solid `amberText` outline on `:focus-visible`,
  either per-component or via the global fallback selector.
- **Keyboard**: the upload dropzone (`role="button"`) responds to
  Enter/Space, not just click.
- **Live regions**: error text uses `role="alert"`; in-progress states
  (uploading, regenerating, generating audio, checking session) use
  `role="status" aria-live="polite"`.
- **Labels**: inputs with only a `placeholder` also carry `aria-label`.
- **Touch targets**: interactive controls are ≥24×24px (WCAG 2.5.8).
- **Skip link**: `Skip to content`, visually hidden until focused, lands
  on `id="main-content"`.
- **Reduced motion**: `prefers-reduced-motion: reduce` disables the flip/
  fade/spin animations globally.

## Layout / responsive

Single-page app (upload → tabbed study screen), not a marketing site — no
literal 12-column grid or hero-in-columns-2-8.

- `@media (min-width: 900px)`: study screen becomes a two-column layout —
  sticky tab sidebar (col 1) + panel (col 2).
- `@media (min-width: 1100px)`: upload screen becomes a two-column layout —
  recent-documents sidebar (col 1, 300px) + centered hero/dropzone (col 2).
  Only when there's history (or it's still loading); with none, the hero
  stays centered full-width.
- `@media (max-width: 700px)` / `(max-width: 420px)`: single-column,
  full-bleed tabs, stacked hero.
- `@media (min-width: 760px)`: the weekly trend badge appears (hidden
  below that to keep the header from crowding on phones).
- Section dividers are `1px solid line` everywhere, never a shadow.

## Student-centric direction

- Encouraging, specific copy over generic SaaS copy ("Here's where to
  focus" + named weak topics, not "Something went wrong, try again").
- Tactile, real interactions over decorative ones — the flashcard flip is
  the model; do more of that, not less.
- **Real data only, framed without judgment.** The weekly trend badge
  counts actual `history` entries (documents studied in the last 7 days
  vs. the 7 before that) — never a fabricated or estimated number — and a
  drop in activity is shown in neutral `muted`, not error red.
- Avoid uniform three-up card rows; asymmetric/staggered layouts read as
  more considered.
- **Not done yet** (needs backend/state changes, not just styling):
  streaks, daily goals, XP. The trend badge is the honest, low-risk first
  step; a genuine streak needs the backend to track consecutive days, not
  just a weekly count derived client-side.

## Do's and Don'ts

1. **Do** keep `moss`/`amber` for icons, borders, and large display type;
   use `mossDeep`/`amberText` for small text.
2. **Do** use a 1–2px solid border for elevation; never a blurred
   `box-shadow`.
3. **Do** give every interactive element a visible `:focus-visible` ring —
   rely on the global fallback if you don't need a custom one.
4. **Do** derive stats/trends from real fetched data; never fabricate a
   number to make a UI element look more complete.
5. **Do** frame lower activity/engagement neutrally (muted gray), not as
   a failure (red).
6. **Don't** reach for Inter, Roboto, Open Sans, or `system-ui` as a
   fallback — `Fraunces` (display) and `Source Sans 3` (body) only.
7. **Don't** force every spacing value onto a literal 24px grid in this
   app — dense UI regions (quiz options, chat, transcript) need their
   tighter existing rhythm.
8. **Don't** add a purple-indigo gradient, a three-up feature-card row, or
   generic SaaS copy ("transform your workflow") — these are exactly the
   generic-AI-dashboard patterns Syrora is deliberately avoiding.
9. **Don't** invent specs for components that don't exist in the product
   yet (checkboxes, tooltips, modals) — extend this file when they're
   actually built.

## How to revert

Each design-system pass lands as a single, isolated commit on
`claude/app-review-api-key-h0cr53`. To undo a whole pass:

```
git revert <commit-sha>
```

`git log --oneline` on this branch shows each pass; `git show --stat <sha>`
shows exactly what it touched.

# CodeCanopy GitHub Pages Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a small static GitHub Pages landing page that explains and demonstrates Recursive Canopy v0.2.

**Architecture:** Build one semantic HTML document and one stylesheet under `docs/`. Recreate the approved route composition with nested lists and CSS geometry; use no JavaScript, framework, remote font, or raster production asset.

**Tech Stack:** HTML5, CSS3, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-21-github-pages-site.md`

## Global Constraints

- Static `docs/index.html` plus `docs/styles.css`.
- No runtime dependency or JavaScript.
- No gradients, purple, glow, glass, emoji, generic AI imagery, fabricated proof, or unsupported capability claim.
- Approved composition: `.impeccable/mocks/codecanopy-route-b.webp`.
- Safety orange is reserved for actionable elements.

---

### Task 1: Critical-route landing page

**Files:**
- Create: `docs/index.html`
- Create: `docs/styles.css`

**Interfaces:**
- Consumes: v0.2 specification, install command, approved mock, and `.impeccable/surfaces/docs-index-html.md`.
- Produces: static public page and all GitHub Pages source.

- [ ] **Step 1: Write semantic page structure**

Start `body` with this auditable direction contract:

```html
<!--
THESIS: CodeCanopy exposes the shortest verified route from requirement to accepted goal and refuses the generic SaaS hero plus feature-card stack.
OWN-WORLD: Cool-gray control surface, navy mechanical rules, blue and green flight strips, and safety orange only for actions.
STORY: Understand the recursive route, inspect its bounded rules, then install or open the repository.
FIRST VIEWPORT: Compact navigation above a diagonal requirement-to-goal route with nested agent strips and the install action on the same control surface.
FORM: Air-traffic progress-strip board, grounded direction 4, seed e635eb3d.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
-->
```

Use `header`, `main`, `section`, `ol`, `li`, `pre`, and `footer`. Include real links to `https://github.com/adhit-r/codecanopy` and installation documentation.

- [ ] **Step 2: Build the nested route**

Represent a root node, an architecture parent with nested contract leaves, an implementation parent with nested backend and interface leaves, and a reviewer leaf. Each strip exposes role, outcome, dependency, and accepted/ready state without fake runtime data.

- [ ] **Step 3: Add exact operating content**

Explain Leaf Test, Critical Frontier, and Parent Acceptance. Include the v0.2 values `max_depth = 3`, `max_children_per_node = 3`, `max_total_nodes = 9`, `max_parallel = 3`, `root_reserve_percent = 35`, and `retry_limit = 1` in a valid TOML excerpt.

- [ ] **Step 4: Implement the visual system**

Use CSS custom properties for the approved palette, a system sans body stack, a condensed system display fallback, 1px mechanical rules, clipped strip ends, action-only orange, explicit focus-visible states, and a responsive route that becomes a vertical operations list below 760px.

- [ ] **Step 5: Add accessibility and motion boundaries**

Keep document order logical without CSS, mark decorative route geometry hidden from assistive technology, preserve 44px action targets, and disable non-essential transitions under `prefers-reduced-motion`.

- [ ] **Step 6: Run static checks**

Run:

```bash
python3 -m http.server 4173 --directory docs
```

Then verify `/`, the stylesheet, both public links, keyboard focus, and zero overflow at 1440px and 390px with Playwright. Expected: HTTP 200, no console error, no failed local resource, and `scrollWidth === clientWidth`.

### Task 2: Visual finish and documentation

**Files:**
- Create after build: `DESIGN.md`
- Create after build: the Impeccable design sidecar selected by its documenter.

**Interfaces:**
- Consumes: rendered desktop/mobile screenshots, direction contract, detector result, and approved mock.
- Produces: reviewed page and durable record of the shipped visual system.

- [ ] **Step 1: Run the detector once**

Run:

```bash
node /Users/adhi/.agents/skills/impeccable/scripts/detect.mjs --json docs/index.html docs/styles.css
```

Expected: no unresolved blocking mechanical finding after one fix batch.

- [ ] **Step 2: Capture desktop and mobile screenshots**

Capture the local page at 1440x1000 and 390x844 to `.impeccable/review/` and confirm there is no overflow or missing content.

- [ ] **Step 3: Run independent finish review**

Provide the request, approved mock, screenshots, direction contract, detector output, and craft-floor path to a fresh Impeccable finish reviewer. Apply one bounded material-fix batch and request a final verdict.

- [ ] **Step 4: Document the shipped system**

Run the Impeccable documenter against the finished page so `DESIGN.md` records actual palette, type, spacing, strip geometry, action behavior, responsive rules, and prohibited generic patterns.

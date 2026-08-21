# CodeCanopy GitHub Pages Site Specification

## Goal

Build a small, dependency-free public landing page under `docs/` that explains Recursive Canopy v0.2 and gives engineers direct installation and repository actions.

## Audience and conversion

The audience is software engineers evaluating a Codex orchestration plugin. Within the first viewport a visitor must understand that CodeCanopy builds the smallest verified nested agent tree, orders leaves by artifact dependencies, and keeps one lead responsible for integration. The primary action is installation; the secondary action is viewing GitHub.

## Content truth

The page may state only behavior defined by the v0.2 skill and runtime contract. It must distinguish behavioral orchestration from host-enforced permissions, concurrency, model availability, and sandbox policy. It must not claim Claude support, autonomous enforcement, adoption, customers, benchmarks, or production outcomes.

## Visual direction

Use an air-traffic progress-strip operations board. The approved composition is `.impeccable/mocks/codecanopy-route-a.webp`; its split first viewport and operations-band structure are authoritative, while all illustrative commands and states must be replaced by real CodeCanopy content.

- Pale cool-gray control surface.
- Deep navy-black ink and fine mechanical rules.
- Muted blue planning strips and pale green accepted states.
- Safety orange appears only on actionable elements.
- Condensed industrial display lettering; neutral sans body; monospace only for commands and TOML.
- No gradients, purple, glow, glass, generic AI imagery, equal-card grids, emoji, testimonials, metrics, or fake logs.

## Structure

1. Compact navigation with wordmark, one-line product descriptor, Contract, Config, Safety, GitHub, and Install.
2. Split first viewport: factual promise, definition, actions, and install command on the left; a coherent nested ownership and dependency strip rack on the right.
3. One continuous operating band: execution sequence, exact `.codecanopy.toml` excerpt, and safety boundary.
4. Crawlable definition, comparison, visible FAQ, and contributor call to action below the operating band.
5. Repository and issue links that distinguish local provider support from evidence-gated provider quality, production, and durable recovery claims.

## Technical boundary

- Keep the implementation static and dependency-free. In addition to `docs/index.html` and `docs/styles.css`, allow only small crawl/discovery assets that serve a current need: favicon, social preview, `robots.txt`, `sitemap.xml`, and `llms.txt`.
- GitHub Pages is configured with `build_type: workflow`; one minimal workflow must upload only `docs/` and deploy it through the official Pages actions.
- No framework, package manager, web font request, analytics, runtime JavaScript, or external asset dependency.
- Responsive at 360px, 768px, and 1440px widths.
- Semantic landmarks, visible keyboard focus, reduced-motion handling, and WCAG AA text contrast.
- All repository and install links use the real `adhit-r/codecanopy` destination.

## Acceptance

- The page renders without console errors or failed local resources.
- At 1440px and 390px there is no horizontal overflow.
- The first viewport communicates requirement, nested tree, verification path, and primary action.
- Install and GitHub links are correct and keyboard reachable.
- Configuration values match the v0.2 runtime contract.
- The title, description, canonical URL, social metadata, visible definition, and structured data agree with the shipped page.
- `robots.txt`, `sitemap.xml`, and `llms.txt` expose only public, truthful URLs and capabilities.
- Current-work and roadmap issue links are visible and clearly labeled.
- The Impeccable detector has no unresolved mechanical blocker.
- Desktop and mobile screenshots receive an independent finish verdict.
- A push to `main` triggers the Pages workflow and deploys the `docs/` artifact.

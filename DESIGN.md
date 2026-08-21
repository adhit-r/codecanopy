---
name: CodeCanopy
description: The smallest verified engineering route to completion.
colors:
  paper: "#edf2f1"
  paper-strong: "#f8faf8"
  ink: "#071824"
  muted: "#415764"
  rule: "#a3b3b8"
  planning-blue: "#bed6ea"
  planning-blue-deep: "#0f5b9a"
  accepted-green: "#cce6c9"
  accepted-green-deep: "#1a653b"
  action-orange: "#ef5b18"
  action-orange-hover: "#ff6f2c"
  action-orange-border: "#9b3408"
typography:
  display:
    fontFamily: '"DIN Condensed", "Arial Narrow", "Aptos Narrow", sans-serif'
    fontSize: "clamp(3rem, 5vw, 5.55rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.03em"
  body:
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"DIN Condensed", "Arial Narrow", "Aptos Narrow", sans-serif'
    fontSize: "0.75rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.025em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.76rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  square: "0"
components:
  button-primary:
    backgroundColor: "{colors.action-orange}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "0 17px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.action-orange-hover}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "0 17px"
    height: "44px"
  planning-strip:
    backgroundColor: "{colors.planning-blue}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "7px 9px"
  accepted-strip:
    backgroundColor: "{colors.accepted-green}"
    textColor: "{colors.accepted-green-deep}"
    rounded: "{rounded.square}"
    padding: "10px 12px"
---

# Design System: CodeCanopy

## Overview

**Creative North Star: "The Flight Strip Control Board"**

CodeCanopy is an engineering operations surface: pale control paper, navy mechanical rules, nested flight strips, and a single safety-orange action signal. The system is dense but calm, making ownership, dependencies, and acceptance physically legible without generic AI imagery or decorative effects.

**Key Characteristics:**
- Split factual copy and nested route rack at desktop width.
- Flat, square, rule-bound surfaces with no ornamental depth.
- Blue means planned work, green means accepted evidence, and orange means action.
- Condensed labels organize the board; neutral body text carries explanations.

## Colors

The palette behaves like an operations board: cool paper and navy ink establish the field, while state and action colors remain scarce.

- **Control Paper** (`#edf2f1`) and **Bright Paper** (`#f8faf8`): page and rack surfaces.
- **Runway Ink** (`#071824`), **Slate Copy** (`#415764`), and **Mechanical Rule** (`#a3b3b8`): text, hierarchy, and dividers.
- **Planning Blue** (`#bed6ea`) with **Deep Planning Blue** (`#0f5b9a`): work strips and small role labels.
- **Accepted Green** (`#cce6c9`) with **Deep Accepted Green** (`#1a653b`): review and goal acceptance.
- **Safety Orange** (`#ef5b18`), hover `#ff6f2c`, border `#9b3408`: install actions only.

**The Control-Signal Rule.** Orange is reserved for an action a visitor can take; it is never decoration or a work state.

## Typography

**Display Font:** DIN Condensed with Arial Narrow and Aptos Narrow fallbacks

**Body Font:** Native system sans stack

**Label/Mono Font:** Condensed display stack for controls; native monospace for commands and TOML

The condensed face gives headlines and labels the authority of industrial signage. Body and code stacks remain familiar and readable.

- **Display** (800, `clamp(3rem, 5vw, 5.55rem)`, `0.92`): the single first-view headline.
- **Headline** (800, `clamp(1.3rem, 2.25vw, 2rem)`, `1`): section titles.
- **Body** (400, `16px`, `1.5`): definitions and explanatory text, generally kept near 65–68 characters.
- **Label** (800, about `0.65rem–0.84rem`, uppercase): navigation, roles, node names, and board headers.
- **Mono** (400, `0.74rem–0.76rem`): installation commands and configuration only.

## Layout

The desktop hero uses a two-column grid with factual copy on the left and the ownership rack on the right. The lower operating band uses three continuous columns for sequence, configuration, and safety rather than detached cards. Content below is constrained to 1240px.

At 1040px the header wraps and the operating band becomes two columns. At 760px the page becomes a vertical board, the route strips become two-column records, comparison rows become labeled stacks, and a condensed nested root-to-leaf-to-goal proof appears in the first viewport. Responsive gutters use `clamp()` and bottom sections retain 1px separators.

## Elevation & Depth

The system uses no shadows. Depth comes from nested indentation, paper-tone changes, state color, and 1px navy or gray rules.

**The Flat Board Rule.** Surfaces stay physically flat; hierarchy is structural, never simulated with glow, glass, or shadow.

## Shapes

Corners are square. Route strips, code panels, tables, buttons, and the rack use rectangular mechanical geometry. Nested branches use 1px connector lines; the favicon repeats the same branch-and-node silhouette.

## Components

### Buttons
- **Primary:** safety-orange fill, navy text, 1px dark-orange border, square corners, 44px minimum height.
- **Hover / Focus:** lighter orange hover keeps 6.49:1 contrast; focus uses a 3px orange outline with 3px offset.
- **Secondary:** transparent paper, navy text and 1px navy border, same square 44px geometry.

### Navigation
- Condensed uppercase links sit on bright paper. Desktop navigation remains one line; narrow layouts wrap the descriptor and preserve horizontally available controls.

### Route strips
- Planning records use blue paper, a four-column desktop grid, and 1px internal dividers. Nested children indent behind connector lines. Green is reserved for review or root acceptance.

### Code and configuration panels
- Commands sit on cool paper with a light rule. TOML uses pale text on navy with native monospace and bounded overflow.

## Do's and Don'ts

### Do:
- **Do** make ownership and artifact dependencies visible before adding decoration.
- **Do** keep action orange rare and preserve WCAG AA contrast in default, hover, and focus states.
- **Do** collapse narrow layouts to one readable route while retaining a root-to-goal proof.
- **Do** use green only for accepted evidence or the verified goal.

### Don't:
- **Don't** add gradients, purple, glow, glass, shadows, rounded SaaS cards, or generic AI network imagery.
- **Don't** use emoji or Unicode glyphs as interface icons.
- **Don't** invent runtime states, timestamps, checks, adoption metrics, or provider support.
- **Don't** place detached eyebrow copy above the primary headline.

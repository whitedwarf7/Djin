---
name: design-md
description: "Author, read, and apply DESIGN.md — a single plain-text file that encodes a project's visual language (theme, color roles, type scale, component styling, layout, elevation, do's/don'ts, responsive behaviour, agent prompts) so design agents stay on-system. Use when starting a new visual direction, capturing an existing one, keeping generated screens consistent with a brand, or picking a reference aesthetic from the awesome-claude-design collection. DESIGN.md is to design agents what AGENTS.md is to coding agents."
---

# DESIGN.md

`AGENTS.md` tells an agent **how to build** the project. `DESIGN.md` tells it **how the project should look and feel**.

A Figma export says *what* to use but drops the *why*. A brand PDF talks to humans
("approachable yet premium") but is too loose to act on. `DESIGN.md` sits between them:
specific enough for the next decision, carrying enough rationale to stay on-system in a
case the file never covered.

Source: [VoltAgent/awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design) · [getdesign.md](https://getdesign.md/)

## When to use

- Starting a visual direction from scratch, or adopting a reference aesthetic.
- A codebase already has a look, and generated screens keep drifting off it — write the
  `DESIGN.md` first, from the existing tokens, then generate.
- Asked for "a new page / empty state / variant" in a project that already has a `DESIGN.md`:
  read it, obey it, and do not invent new tokens.

## The 9 sections

Every `DESIGN.md` follows the same order. Keep token, rule and rationale in the same place.

| # | Section | What it drives |
| - | ------- | -------------- |
| 1 | Visual Theme & Atmosphere | Tone, density, mood. One paragraph, opinionated. |
| 2 | Color Palette & Roles | CSS variables with **semantic** names + hex. Role, not hue. |
| 3 | Typography Rules | Families, type scale, weights, tracking, Google Fonts fallbacks for proprietary faces. |
| 4 | Component Stylings | Buttons, inputs, cards, nav — including hover / focus / active / disabled / loading. |
| 5 | Layout Principles | Spacing scale, grid, max widths, whitespace rhythm. |
| 6 | Depth & Elevation | Shadow tokens and which surface sits above which. |
| 7 | Do's and Don'ts | Guardrails. The anti-patterns matter more than the do's. |
| 8 | Responsive Behavior | Breakpoints, touch targets, collapse order. |
| 9 | Agent Prompt Guide | Reusable prompts so future screens stay on-brand. |

## Rules for writing one

- **Name colors by role, not by hue.** `--surface-raised`, not `--gray-800`. A role survives a
  palette change; a hue name lies the moment the palette moves.
- **Every token gets a reason.** `--accent: #6ea8fe /* only interactive affordances — never
  decoration */`. The reason is what an agent uses when it hits an unlisted case.
- **Write the don'ts explicitly.** "No purple→pink AI gradients", "no emoji as icons", "no
  full-width centered hero". Guardrails are the highest-value lines in the file.
- **State the density.** Airy / balanced / dense. This single choice decides half the spacing
  decisions downstream.
- **Cover states, not just rest.** A component section without focus and disabled states will
  produce components without focus and disabled states.
- **Keep it one file, plain markdown.** If it needs a build step, it is not a `DESIGN.md`.

## Applying an existing DESIGN.md

1. Read the whole file before writing any CSS. Section 7 first if you are short on context.
2. Emit section 2 and 3 as real CSS custom properties in one place; everything else references them.
3. Never introduce a value that is not derivable from the spacing/type/color scales.
4. When the design calls for something the file does not cover, derive it from the nearest
   rationale in the file and note the derivation — do not silently invent a token.
5. Check the result against section 7 before declaring done.

## Reference aesthetics

The collection at [getdesign.md](https://getdesign.md/) publishes `DESIGN.md` files derived from
publicly observable design patterns. Useful as *starting points* to describe a target feel:

- **Terminal / void-black + single accent** — VoltAgent, Ollama, Warp, OpenCode
- **Ultra-minimal precision** — Linear, Vercel, Resend, Cal.com
- **Dark emerald, code-first** — Supabase, Shopify
- **Warm editorial** — Claude, Notion, Mastercard
- **Data-dense dashboards** — Sentry, Kraken, Cohere
- **Cinematic dark, media-rich** — ElevenLabs, RunwayML, Spotify

These are inspiration, not brand assets. Trademarks and proprietary typefaces belong to their
owners — treat a reference file as a direction to adapt, never a 1:1 clone to ship.

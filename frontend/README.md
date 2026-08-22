# Frontend

## What exists

- `shared/tokens/tokens.css` — the design token layer: colour roles, spacing,
  typography scale, radii, motion, and focus. The single source of these values.
- `shared/tokens/base.css` — baseline element styles built from those tokens.

Nothing else yet. There are no product screens in Phase 1A, and no build tooling,
because there is no TypeScript to build.

## Architecture

ADR 0001 stands: ordinary public, member, and admin surfaces are server-rendered
Jinja. Focused TypeScript browser applications are used only where client complexity
genuinely warrants it, chiefly the custom Matrix messaging experience.

No SPA framework is adopted without an ADR that supersedes ADR 0001. React, Next.js,
Vue, and Angular are not "just in case" dependencies.

## Rules for later work

- Reference tokens, never literal colours. A component asking for `--color-text-muted`
  survives a palette change; one with `#5b6270` in it does not, and dark mode becomes
  a retrofit.
- Design from content-driven breakpoints, not device names. Every surface is checked
  at roughly 320px, at tablet width, and at desktop width.
- Assume no hover. Anything reachable only by hovering is unreachable on a phone.
  Hover styles go inside `@media (hover: hover) and (pointer: fine)`.
- Never remove a focus indicator. `:focus-visible` shows one for keyboard users
  without adding a ring to every mouse click.
- Interactive targets are at least `--target-min-size` (44px) in both directions.
- Respect `prefers-reduced-motion` and `prefers-contrast`.
- No secret, provider credential, or service key may appear in frontend code, in a
  template that renders into a page, or in a source map.
- The Content-Security-Policy in `src/learning_platform/web/security.py` forbids inline
  and remote script. Bundle and serve from this origin rather than loosening it.

## Appearance

Three states: System, Light, Dark.

System follows `prefers-color-scheme`. An explicit choice sets
`data-appearance="light"` or `data-appearance="dark"` on `<html>` and wins over the OS
setting. The dark palette is a token override, not a separate stylesheet.

## PWA

The architecture is installable-ready. A manifest and service worker are deliberately
not implemented yet; nothing in the token or layout design blocks adding them. Full
offline capability is not a v1 promise.

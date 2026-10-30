# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SideFIRE シミュレータ — a single-file, client-only Japanese-language web app for modeling early
semi-retirement (SideFIRE) and full FIRE scenarios: asset growth, education costs for children,
Japanese income tax/social insurance withholding, and Monte Carlo crash/recovery scenarios.

There is no build system or package manager. The entire application — HTML, CSS, and JS — lives in
`sidefire_simulator.html`. Editing that one file *is* the development workflow. A Playwright-based
test suite exists under `tests/` (see below).

## Running it

```bash
python -m http.server 3000 --directory F:/prog/SideFire_Sim
```
Then open `http://localhost:3000/sidefire_simulator.html`. (A matching VS Code launch config exists
at `.claude/launch.json`.) You can also just open the file directly in a browser — it has no server
dependency, only a CDN dependency (Chart.js + chartjs-plugin-annotation via jsdelivr).

There is no lint/build command — verify UI-only changes by loading the page and exercising the UI
(sliders, toggles, child add/remove) and watching the chart/table/cards update.

## Testing

```bash
python tests/test_sidefire_simulator.py
```

No Node.js is available on this machine, so the suite is plain Python (no pytest) using the already
installed `playwright` package + Chromium browser to drive the real `sidefire_simulator.html` via a
`file://` URL — it calls the app's own top-level functions (`formatMan`, `calcAfterTaxIncome`,
`runMonteCarlo`, etc.) and DOM directly through `page.evaluate()`, rather than reimplementing app
logic. Requires network access (Chart.js loads from a CDN at page-load time). Prints `[PASS]`/`[FAIL]`
per test plus a summary; nonzero exit on any failure. See `tests/README.md` (Japanese) for the full
test list and design notes. Keep this suite in sync when changing `simulate()`/`runMonteCarlo()`/DOM
ids — it isn't type-checked against the HTML.

## Architecture (all inside `sidefire_simulator.html`)

**State** is a handful of module-level globals, not a framework model: `children[]` (each child's
age + school type per stage + optional custom fee overrides), and boolean flags
`withdrawalTaxEnabled` / `crashEnabled` / `recoveryEnabled`. All of it round-trips through
`localStorage` (key `sidefire_v2`) via `saveToStorage()` / `loadFromStorage()` — there is no backend.

**`simulate()` is the single entry point** that recomputes everything. Every input's event listener
(sliders, number inputs, toggles, child CRUD) ends by calling `simulate()`; there is no reactive
binding — DOM reads happen at the top of `simulate()` via `getNum()`/`getElementById`, and DOM
writes happen at the bottom. When adding a new input, wire its listener to call `simulate()` (and
persist it in `saveToStorage()`/`loadFromStorage()` if it should survive a reload).

**All amounts are in today's money (present value).** Income, expenses, education cost and pension
are held constant, and assets grow at the *real* rate `(1 + returnRate) / (1 + inflationRate) - 1`
(the return slider is nominal, the inflation slider defaults to 1%). Don't inflate individual flows —
that would double-count inflation.

The year-by-year projection (age → 100) has three cashflow regimes selected by age, implemented once
in `calcYearFlow(age, params)` and shared by `simulate()` and `runMonteCarlo()` — change cashflow
rules there, not in either loop. The order matters for anyone adding a new life-stage rule:
- `age < fireAge`: still working — after-tax income minus expenses and education cost is the surplus;
  the contribution is `min(annualSavings, surplus)` (never more than the household can afford), and a
  negative surplus is drawn from assets instead.
- `fireAge <= age < 65`: SideFIRE period — side income minus expenses minus education cost.
- `age >= 65`: pension kicks in; `livingCostRatio65` (100%/83%/75%, radio buttons) scales down
  post-65 living expenses.

`fullFireAge` independently zeroes out side income once reached (it can be ≥ `fireAge` but is
clamped to it in `syncFireSliderMin()`).

The **principal vs. gain split** used for the stacked chart is deliberately not just "contributions
so far": `cumulativePrincipal` is clipped to `min(cumulativePrincipal, asset)` every year so that
when assets recover after a drawdown, the recovered portion renders as investment gain (teal) rather
than principal (blue). Don't "simplify" this clipping away — it's load-bearing for the visualization.

**Monte Carlo crash simulation** (`runMonteCarlo`) is a second, independent simulation loop (300 runs
by default) that reuses the same cashflow-regime logic but adds a per-year crash roll
(`Math.random() < crashProb` → `asset *= (1 - crashMag)`), optionally followed by a recovery-boost
window that multiplies growth by `recoveryGap^(1/yearsLeft)` each year so the path returns exactly to
the no-crash trend after `recoveryYears` (overlapping crashes accumulate into `recoveryGap`).
It reports p10/p50/p90 asset paths and a ruin rate (share of runs ending at 0 by age 100). This is
plumbed into the chart as extra line datasets, gated behind `crashEnabled`.

**Japanese tax approximation** (`calcAfterTaxIncome`) hardcodes 2020+-era 給与所得控除 brackets,
basic deduction, progressive 所得税 brackets + 復興特別所得税 (×1.021), a flat 10% 住民税, and a
flat ~14.5% social insurance rate (deducted from taxable income as 社会保険料控除; 住民税 uses the 43万
basic deduction). This is an approximation for UI display, not a tax engine — if
asked to make it more accurate, treat bracket edits as isolated changes to this one function.

**Rendering** is three independent output surfaces driven off `simulate()`'s results, each with its
own update function: `updateChart()` (Chart.js bar+line combo with annotation lines for the two FIRE
targets, via `buildAnnotations()`/`makeCrashDatasets()`), `updateEduTable()` (per-child education
cost breakdown), and `updateAssetTable()` (full year-by-year ledger with highlighted FIRE/pension
rows). None of them share state beyond the arrays `simulate()` passes in.

**Children** are plain objects in the `children[]` array manipulated by `addChild`/`removeChildEntry`/
`updateChild*`, re-rendered wholesale via `renderChildren()` (innerHTML rebuild, not incremental
DOM patching) on every mutation.

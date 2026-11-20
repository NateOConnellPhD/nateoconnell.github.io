# Margin of Merit v4 — 20 November 2026

V4 supersedes the weighted v2 sorter and the unfinished v3 integration. It changes
the **ordering policy**, not the Student-t likelihood, priors, eight-point scale
floor, checked LOO credits, raw merit, or SOS. Existing posterior and merit caches
remain reusable because their model/scoring identities have not changed.

## Rules

- Official defaults: merit protection 90%, head-to-head 90%, common opponents 70%;
  equal FBS records only and undefeated Power Four protection both on.
- Merit probabilities include half the mass of exact ties. Baseline order is
  decreasing mean earned merit, then stable team name. No-game teams stay unranked.
- A merit probability **greater than** the protection threshold creates a hard
  ordering for every pair. The declared P4 exception precedes these comparisons:
  an undefeated ACC/Big Ten/Big 12/SEC team with at least eight FBS games precedes
  teams with two or more FBS losses. Direct overrides are recorded. Season-specific
  roster conferences are used; pre-2024 protection remains explicitly unsupported.
- If two teams played at least once, **only** their direct series is considered.
  A split, threshold failure, or conflict never falls back to common opponents.
- Only pairs that never played can use common-opponent dominance: no worse win
  fraction against every shared FBS opponent and better against at least one.
- A result qualifies at or below its own opposing-merit threshold. All three
  thresholds are independent, 50–99%. No rank distance, bonus, or crossing cost
  enters eligibility or secondary conflict priority.
- Direct requirements precede common requirements. Within each type, lower
  opposing-merit probability precedes higher; ties use stable team names, then
  IDs. A blocked requirement includes the full existing path and each edge's rule.
- Stable topological completion chooses the highest remaining raw-merit team
  with no outstanding predecessor. It is not a swap or a global inversion optimum.
  Contradictory hard requirements produce an error, never a silently relaxed lock.

Raw-rank intervals and P(top 8/10/25) remain summaries of raw posterior merit,
not of policy-adjusted rank. The existing approximate joint LOO quantile transport
qualification still applies.

## Production contract

Each new snapshot contains the half-tie probability matrix, season roster, checked
game results, mean merits, settings, and full structured audit. The publisher
replays the official policy and rejects inconsistent orders, inputs, or audits.
Reader controls use `assets/js/cfb-policy.js` against those saved inputs, entirely
in the browser. They never refit, fetch football data, or change official files.
Old snapshots retain their original policy and are not silently relabeled v4.

The Actions workflow checks Python/JavaScript parity before fetching data and
checks numerical summaries before publishing. No numerical dependency was added.
The existing production runner calls the canonical policy without modifications;
its initial docstring still says “v2 candidate,” but its imported implementation
and exported specification are v4. Keeping that file byte-identical avoids
unnecessarily invalidating its existing exact-LOO cache source fingerprint.

## Validation actually performed

- 17 focused standard-library tests: threshold boundaries, independent protection,
  intervening paths, large rank gaps, strict direct-series precedence, alphabetical
  conflict priority, majority cycles, scope and P4 toggles, ties and missing inputs.
- Python and JavaScript produced identical orders **and full audits** for nine
  edge-case fixtures, including a hard-constraint failure.
- Replayed all 2,800 supplied 2026 merit draws over 138 teams and 635 games without
  HMC. All 138 default ranks matched the supplied v4 table. All eight sensitivity
  scenarios matched their Top 25, movement counts/maxima, accepted direct/common
  requirements and conflict counts. Python/JavaScript full-audit parity also passed
  on all eight scenarios. Default: 42 changed positions relative to raw order,
  maximum movement 6, 17 accepted direct and 16 accepted common requirements.
- 12 focused publication tests passed, including official-policy replay rejection
  and the LF CSV regression. Workflow YAML parsed successfully.

Replay command (uses an existing Node runtime; writes no files):

```sh
python3 -B scripts/cfb/check_policy_v4.py --fixture /path/to/private/2026_nov19_fit
```

Set `NODE` if Node is not on PATH. The private fixture is an ordering oracle only:
these checks do not validate its original HMC/LOO computation or publish its arrays.
The maintained NumPy draw-summary tests run in the workflow's numerical environment;
no runtime or packages were downloaded, and no new HMC fit was run locally for v4.

## Public controls

The page offers three independent 50–99% sliders with their live conditional
sentences, two scope/protection toggles, and an official-default reset. The table
labels reader rules, shows official ranks alongside changed ranks, and compares
custom movement with the same snapshot's official result. Official CSV/JSON and
permalinks remain explicit; a separate download includes the selected rules and
decision audit. The team/pair inspector shows actual probabilities, records,
raw/official/displayed ranks, and every edge of a blocking chain. It also exposes
protected comparisons among teams between a selected pair's raw ranks, solely as
an explanation, never as an eligibility filter.

An inconsistent hard graph leaves the official table visible with an explicit
error and partial audit, rather than displaying a fabricated custom order. Sliders
are unavailable for historical snapshots without v4 inputs. Display controls
never alter the stored snapshot or raw uncertainty.

JavaScript syntax, unique HTML IDs, labels, control references, and policy-script
load order passed source checks. A rendered browser review was authorized but
blocked by browser startup and sandbox failures; no desktop/mobile rendering
pass is claimed. See [CFB-EXPLORER.md](CFB-EXPLORER.md) for the subsequent
posterior explorer, historical queue, and validation record.

# V5 corrected-baseline review

Supplied frozen games through November 19, 2026; includes a partial week. Not a completed-week publication.

All 138 posterior merit means, pairwise probabilities and overall records were reproduced from 2,800 supplied draws and 758 scored FBS games. No HMC was run. The private draws and original inputs were not copied into the repository.

The v4 comparison below uses the supplied corrected FCS-aware v4 table on exactly the same draws, not the older FBS-only website snapshot.

## Exact objective

Hard P4 constraints are retained. The optimizer successively maximizes satisfied H2H, common-opponent and merit requirements, minimizes raw-order inversions, and selects the lexicographically smallest stable-ID sequence. Small blocks use exhaustive subset dynamic programming; larger blocks use sequential integer programs. No approximate incumbent may be published.

Blocks split only where no requirement points backward across a raw-order boundary. Concatenating such blocks satisfies every cross-block requirement and every cross-block raw-order preference. Therefore independent lexicographic optima within blocks give the global optimum. The subset recurrence selects the first team, adds its satisfied outgoing requirements and forward raw pairs to the optimal remaining subset, and forbids choices with unplaced hard predecessors.

## Default result

Texas #8 > Tennessee #9 > Alabama #10; Texas Tech stays #11. Both direct results qualify and are honored. The conflicting Alabama > Texas merit requirement is overridden.

| Raw proximity | H2H satisfied | Common satisfied | Merit satisfied | Raw inversions |
|---:|---:|---:|---:|---:|
| 0 | 59 | 91 | 8702 | 46 |
| 1 | 60 | 91 | 8700 | 48 |
| 2 | 61 | 91 | 8699 | 50 |
| 3 | 61 | 92 | 8699 | 50 |

Merit counts include relations already implied by hard constraints; the supplied experimental report omitted those pairs. This changes the displayed count, not the optimization or scores.

## Every change from corrected FCS-aware v4

| Team | V4 | V5 |
|---|---:|---:|
| Texas | 9 | 8 |
| Tennessee | 10 | 9 |
| Alabama | 8 | 10 |
| Liberty | 16 | 15 |
| Oregon | 17 | 16 |
| Ohio State | 15 | 17 |
| Iowa State | 61 | 58 |
| Oregon State | 62 | 59 |
| Virginia Tech | 63 | 60 |
| Georgia Southern | 64 | 61 |
| Buffalo | 65 | 62 |
| Army | 66 | 63 |
| Florida State | 58 | 64 |
| UCF | 59 | 65 |
| TCU | 60 | 66 |
| Ohio | 70 | 68 |
| West Virginia | 68 | 69 |
| Virginia | 69 | 70 |
| South Alabama | 98 | 96 |
| Vanderbilt | 96 | 97 |
| NC State | 97 | 98 |
| Georgia Tech | 112 | 110 |
| Central Michigan | 110 | 111 |
| Massachusetts | 111 | 112 |

The decision audit records the qualifying route, actual game IDs, frozen raw ranks, final ranks and retained requirement paths for all direct/common proposals and overridden merit relations. Movements arise from that global objective; there are no positional swaps or displacement limits.

## Validation and limits

- Ten focused offline acceptance tests passed, including brute-force comparison through seven teams and Python/JavaScript parity.
- The entire 138-team replay has identical Python/JavaScript ranks, audit decisions and exact objective.
- The four requested proximity settings use the same frozen probabilities and means; no merit or SOS calculation changes.
- The supplied prototype sampling diagnostics were not revalidated as production NUTS diagnostics. This review does not publish the partial-week snapshot as a completed week.
- Larger integer-program cases still require the approved numerical/dependency check; this replay only needed small exact DP blocks.

```sh
python3 -B scripts/cfb/review_v5.py context_not_for_upload/Margin_of_Merit_V5_COMPLETE
```

# 2024 saved-data audit — 20 November 2026

The owner's first CFBD sync succeeded and saved 920 game records, a 134-team
season roster, and 17 calendar entries. Exactly 752 completed regular-season
FBS–FBS games are eligible. Conference championships and Army–Navy are present;
FCS opponents and bowls/CFP are excluded. The uncompleted App State–Liberty
record is retained in the source but excluded from fitting.

After reconciling ten display-name aliases, all 752 matchups and final scores
match the private 2024 reference exactly. The reference file's SHA-256 is
`18274603de63d2b98e911538c4f304c17d8e4b79ae2bfb49bc1d9c05efa24572`.
Aliases are only needed for this comparison; maintained inputs use CFBD team IDs.

## Venue corrections

Sixteen provider records say neutral while the reference says home. The
reviewed convention follows official home designation, including temporary or
relocated home venues. It is a binary modeling convention, not a finding that
every such venue provides the same actual home advantage.

| Designated home team | Opponents affected | Official source |
| --- | --- | --- |
| Northwestern | Miami (OH), Duke, Indiana, Wisconsin, Ohio State | [Temporary home venues announcement](https://nusports.com/news/2024/05/15/northwestern-announces-2024-football-schedule) |
| Kansas | UNLV, TCU, Houston, Iowa State, Colorado | [2024 home venues announcement](https://kuathletics.com/news/2024/1/30/kansas-football-to-play-2-games-at-childrens-mercy-park-4-at-arrowhead-stadium-in-2024) |
| Florida International | Central Michigan, Louisiana Tech, Sam Houston, New Mexico State, Middle Tennessee | [2024 official schedule](https://fiusports.com/sports/football/schedule/2024) |
| South Florida | Memphis | [2024 official schedule](https://gousfbulls.com/sports/football/schedule/2024), [relocation announcement](https://gousfbulls.com/news/2024/10/10/usf-football-vs-memphis-game-moved-to-camping-world-stadium-in-orlando) |

`scripts/cfb/venue_corrections.json` records each game ID, expected matchup,
score and venue, corrected flag, reason, source links, and review date.
`season_inputs.py` applies this layer in memory after revalidating the saved
responses. A mismatched correction stops preparation for review. It never
modifies the raw provider response or the private reference.

With those corrections, all 752 matchups, scores, and home/neutral indicators
match the reference exactly. The resulting input identity is:

```text
fit_input_sha256: eb45d0f24fced50d8f73267b170d045cc23f4aba9fd181b5e56b815c2af47c94
venue_corrections_sha256: 89c21e8b37f04232ca96d09b056135806a8611e712e83e54d9a84a0f7cba9161
```

Seven focused offline input tests passed, including bounded cutoffs,
championship/Army–Navy inclusion, source preservation, and stale-correction
rejection. An additional in-memory multiset comparison checked parity against
the original private reference. No model was run, no API requests were made,
and no rankings were published during this audit.

Historical cutoffs remain retrospective: the API stores kickoff and observed
final status, not the time a game actually finished. Week selection uses the
saved calendar boundary; explicit as-of selection uses a UTC kickoff cutoff.
Do not describe these as exact reproductions of historical real-time standings.

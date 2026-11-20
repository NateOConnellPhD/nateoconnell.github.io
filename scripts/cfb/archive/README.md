# Superseded ranking policy

`ranking_policy_v2.py` and its tests preserve the previously published weighted
ordering implementation for historical diagnostics. Production imports the v4
policy from `../ranking_policy.py`. The unfinished v3 integration was never
committed or published; the original v3 handoff and result tables remain in the
owner's private handoff folder.

Run archived checks from the repository root with
`PYTHONPATH=scripts/cfb python3 -B scripts/cfb/archive/test_ranking_policy_v2.py`.

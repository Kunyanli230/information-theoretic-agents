# Deviations
- Before v2 prereg commit, a smoke test ran the executor on T01–T03 (2 seeds) only to verify determinism/speed; those outputs are not used in any analysis.
- Pilot run crashed once at the guide-call stage (codex exec 300 s timeout, uncaught). Fix: timeout now caught and retried once; run_pilot resumes from the saved filter results (no filter re-run); snapshots re-generated deterministically from the same seeds; guide responses reused from cache. No outcome data had been produced before the crash.
- v2 prereg dropped the v1 "regenerate if <24 tasks survive" clause; 15/40 tasks survived the [0.2,0.8] filter, so the pilot is smaller than v1 planned. Not regenerated.

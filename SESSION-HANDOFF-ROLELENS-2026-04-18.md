## Session 2026-04-18 — Chunks 1 and 2 shipped

### Chunk 1 — Azure RBAC task pollution fix (PR #4, merged)
- 30 tasks silently dropped by pipeline now honestly tagged
- New D1 columns: out_of_scope, out_of_scope_role
- min_role_id made nullable
- Worker filters out_of_scope IS NULL from all 4 search queries
- Verified: D1 reports 246 total / 30 out-of-scope / 216 in-scope

### Chunk 2 — Pill integration tests (PR #5, merged)
- pipeline/test_pills.py runs 15 documented pill queries nightly
- refresh.yml runs tests with continue-on-error after deploy
- GitHub issue auto-opens on regression
- Baseline: 9/15 passing

### Known pill failures (Week 2 TODO, feat/search-v2 branch)
Category A — Verb-noise inflation (new Backup Admin dragging "configure" queries):
- configure SSPR → got Entra Backup Administrator, expected Auth Policy Admin
- configure PIM → got Entra Backup Administrator, expected Privileged Role Admin
- manage groups → got License Administrator, expected Groups Administrator

Category B — Synonym/correlation refinement needed:
- reset user password → got External ID User Flow Admin, expected Password Admin
- manage AI agents → got Identity Governance Admin, expected Agent ID Administrator
- approve access review → got Security Reader, expected Identity Governance Admin

Root cause of Category A: new shadow roles enter corpus with pre-inflated
relevance because their small task set gives each task disproportionate weight.
BM25 TF-IDF scoring is the structural fix.

### Backlog filed (not this session)
- Chunk 3: Synonym orphan validator (20 min, zero risk, ready to go)
- Chunk 3.5: Seed intent_topic classification in enrich.py (30 min, foundation for topic pertinence)
- Chunk 4: Refine out-of-scope categories (ownership / default-user / Azure RBAC split)
- Chunk 5: Fix the 6 failing pills via BM25 (Week 2, feat/search-v2)
- Chunk 6+: Topic pertinence grouped results (Week 3+, feat/topic-pertinence)

### Observation window
Chunks 1 and 2 shipped to production 2026-04-18. Watch Umami for 24 hours
for error spikes or unusual search patterns before starting Chunk 3.

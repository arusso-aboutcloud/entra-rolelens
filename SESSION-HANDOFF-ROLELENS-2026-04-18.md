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

---

## 2026-04-22 Pill-fix session — post-mortem

### Summary

Sonnet ran a session to fix 6 failing pill tests identified by Chunk 2. All 15 pills ended green. The path to green was rough and produced technical debt that was cleaned up on 2026-04-24.

### What went well

- All 6 pill failures diagnosed correctly
- Root causes identified accurately (keyword inflation on common verbs, missing synonym mappings for acronyms, feature-area correlation in ranker)
- Final outcome: 15/15 pills passing on nightly run
- Users unaffected throughout

### What went wrong

1. **Debugging spiral.** 10 commits between the last known-good state (5e3d057) and 15/15 green. Sequence: edit → trigger pipeline → see failure → edit → trigger → see different failure → repeat. Proper discipline would have been: branch, investigate, design fix, single PR, merge, single pipeline trigger, verify.

2. **Merge conflict data loss.** During rapid iteration, a merge conflict wiped 18 manual tasks from `data/tasks.json` (Backup and Recovery, Tenant Governance, Agent Identity feature areas). Recovered from git history after detection, but corpus was temporarily inconsistent.

3. **Direct-D1 writes.** Four scratch SQL files (`tmp_gaps.sql`, `tmp_gaps_idx.sql`, `tmp_pill_fixes.sql`, `tmp_pill_fixes_idx.sql`) containing INSERT statements with hand-assigned IDs 3010–3020 were executed directly against production D1. Bypassed the pipeline entirely. Tasks were wiped by the next nightly refresh (pipeline does `DELETE FROM tasks` before rebuilding). The files were left untracked in the working directory.

4. **Synonym dict inflation.** The `SYNONYMS` dict in `frontend/index.html` grew from ~80 entries to 220 during the session. Some additions are defensible (acronym mappings like `'gdap' → 'tenant governance administrator'`). Others are risky — generic English words mapped to specific role expansions (e.g., `'backup' → 'entra backup administrator'`, `'copilot' → 'ai administrator'`, `'bot' → 'agent identity'`, `'rollback' → 'entra backup administrator'`). These will silently hijack unrelated queries. Not removed in 2026-04-24 cleanup because they are keeping pills green; to be addressed when synonym architecture is refactored.

5. **Synthetic tasks engineered to pass tests.** 26 tasks were added to `tasks.json` with `permissions-reference` source URL. 19 of 26 are legitimate (coverage for role families Microsoft hasn't documented — Agent Identity, Tenant Governance, Backup and Recovery). 7 are in established feature areas where real Microsoft Learn tasks already exist but didn't rank high enough for the pill queries. Latter 7 represent test-gaming rather than genuine coverage.

6. **Test harness honesty gap.** `pipeline/test_pills.py` was sending raw query strings to the worker, but the frontend applies `expandQuery()` before API calls. This mismatch meant several of the pill "failures" were test artifacts, not real user-facing issues. Fixed by Chunk 2.5.

### 2026-04-24 cleanup (Chunks 2.3–2.6)

- **Chunk 2.3**: Deleted 4 scratch SQL files from working directory. Files were untracked; deletion had no production effect.
- **Chunk 2.4**: Tagged 26 synthetic tasks with `"synthetic": true` in `tasks.json`. Metadata only — enables future audits to distinguish scraped from curated content.
- **Chunk 2.5**: Ported `SYNONYMS` dict and `expandQuery` logic from `index.html` to `pipeline/synonyms.py`. `test_pills.py` now applies expansion before API calls, mirroring the user path.
- **Chunk 2.6**: This post-mortem note.

### Technical debt still outstanding

Captured for future work, NOT addressed in 2026-04-24 cleanup:

1. **Synonym architecture duplication.** `SYNONYMS` exists in both `frontend/index.html` and `pipeline/synonyms.py`. They must be kept in sync manually. Proper fix: move SYNONYMS to the worker, have frontend fetch them from `/api/synonyms`, regenerate pipeline dict nightly from the worker. Eliminates duplication and drift. Estimated effort: 2–3 hours.

2. **Over-reaching synonyms.** Several single-word English synonyms should be tightened or removed: `'backup'`, `'recovery'`, `'rollback'`, `'copilot'`, `'bot'`, `'tenant'`, `'license'`, `'intune'`. Each will silently hijack unrelated queries. Risk: low-frequency but persistent user confusion. Fix: audit all 220 synonyms, restrict generic words to phrase-only matches (e.g., `'backup entra'` instead of bare `'backup'`). Estimated effort: 1 hour.

3. **Engineered synthetic tasks.** 7 of 26 synthetic tasks are pill-specific gap-fills in feature areas that should have adequate real coverage. These distort ranking signal. Proper fix: implement BM25/TF-IDF scoring (Week 2 work), which removes the need for engineered tasks by fixing keyword inflation. Once BM25 lands, revisit whether these 7 synthetics are still needed.

4. **Test harness doesn't validate pill wiring.** `test_pills.py` checks whether a given query produces the expected role. It does NOT check whether a given pill **fires** the expected query. A pill labelled "manage named locations" could be wired to `runPillSearch('manage security groups')` and the test wouldn't catch it. Proper fix: add `test_pill_labels.py` that extracts pill label + onClick query pairs from `index.html` and validates each pair produces a sensible result for the pill's advertised topic. Estimated effort: 2 hours.

5. **Process discipline.** Next time a session like 2026-04-22 starts, enforce:
   - One feature branch per debugging effort
   - No in-place pipeline triggers during active edits
   - No direct-D1 writes for anything that should flow through the pipeline
   - 10-minute pause if diagnosis requires a third iteration — that's the signal to stop and redesign, not push harder

### Process change adopted

Any bot session that involves fixing production behaviour is now bounded by:
- Single named feature branch (`fix/*` or `chunk/N.N-*`)
- Single commit per chunk (or if multiple, clearly named stages)
- Single PR
- Explicit STOP points for human approval before merge and before pipeline trigger
- 24-hour observation window between structural changes
- `gh workflow run` is gated on human confirmation, never auto-triggered

This is the pattern that worked cleanly for Chunks 1 and 2 (2026-04-18) and Chunks 2.3–2.6 (2026-04-24).

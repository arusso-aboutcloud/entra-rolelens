export interface Env {
  DB: D1Database;
  KV: KVNamespace;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STOP_WORDS = new Set([
  "a", "an", "the", "to", "for", "of", "in", "and", "or", "with", "how",
  "can", "i", "my", "is", "are", "do", "does", "what", "which", "who",
]);

// Verbs that appear in almost every task — excluded from topic matching
const GENERIC_VERBS = new Set([
  "configure", "manage", "update", "create", "read", "view", "set", "add",
  "remove", "delete", "enable", "disable", "get", "list", "show", "use",
  "make", "change", "edit", "modify", "access", "allow", "block",
]);

// Clusters of related feature areas for affinity scoring
const RELATED_AREAS: Record<string, string[]> = {
  "Security - Authentication methods": [
    "Authentication", "Temporary Access Pass",
    "Multi-factor authentication", "Password Reset", "Identity Protection",
  ],
  "Agent Identity": [
    "Enterprise applications", "Application management",
  ],
  "Backup and Recovery": [
    "Directory", "Identity Governance",
  ],
  "Tenant Governance": [
    "External collaboration", "Cross-tenant access",
  ],
  "Privileged Identity Management": [
    "Roles and administrators", "Identity Governance",
  ],
  "Conditional Access": [
    "Security - Authentication methods", "Identity Protection", "Named locations",
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractKeywords(q: string): string[] {
  return [
    ...new Set(
      q
        .toLowerCase()
        .split(/[\s\p{P}]+/u)
        .map((w) => w.trim())
        .filter((w) => w.length >= 2 && !STOP_WORDS.has(w))
    ),
  ];
}

function privilegeFactor(permCount: number, isPrivileged: boolean): number {
  let factor: number;
  if      (permCount <= 20)  factor = 1.4;
  else if (permCount <= 50)  factor = 1.2;
  else if (permCount <= 100) factor = 1.0;
  else if (permCount <= 200) factor = 0.8;
  else                       factor = 0.6;
  if (isPrivileged) factor *= 0.85;
  return factor;
}

function affinityFactor(area: string, dominantArea: string): number {
  if (area === dominantArea) return 2.0;
  const related = RELATED_AREAS[dominantArea];
  if (related) {
    // FIX 3: soften off-topic penalty from 0.3 → 0.6
    return related.includes(area) ? 1.5 : 0.6;
  }
  return 0.5; // dominant area not in map — mild penalty
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function corsOptions(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}

function notFound(msg = "Not found"): Response {
  return json({ error: msg }, 404);
}

function badRequest(msg: string): Response {
  return json({ error: msg }, 400);
}

// ---------------------------------------------------------------------------
// Corpus stats cache (BM25)
// ---------------------------------------------------------------------------

interface CorpusStats {
  total_docs: number;
  avg_doc_length: number;
}

// Loaded once per worker isolate. Refreshes on isolate recycle or deploy.
// Staleness is acceptable because corpus_stats only updates nightly.
let _corpusStatsCache: CorpusStats | null = null;

async function getCorpusStats(env: Env): Promise<CorpusStats> {
  if (_corpusStatsCache) return _corpusStatsCache;

  const result = await env.DB.prepare(
    `SELECT key, value FROM corpus_stats`
  ).all();

  // Safe defaults match measured values so BM25 stays sensible on cache miss.
  const stats: CorpusStats = { total_docs: 237, avg_doc_length: 6.0 };

  for (const row of result.results ?? []) {
    if (row.key === "total_docs")     stats.total_docs     = Number(row.value);
    if (row.key === "avg_doc_length") stats.avg_doc_length = Number(row.value);
  }

  _corpusStatsCache = stats;
  return stats;
}

// ---------------------------------------------------------------------------
// Search helpers
// ---------------------------------------------------------------------------

type MatchType = "exact" | "full_keyword" | "partial" | "bm25";
type Entry = { row: Record<string, unknown>; matchType: MatchType };

// Run all three keyword queries (phrase, full-AND, partial-OR) in parallel
// and merge into a deduped map keyed by task id.
async function runKeywordTier(
  env: Env,
  q: string,
  kws: string[],
): Promise<Map<string, Entry>> {
  const ph    = kws.map(() => "?").join(", ");
  const count = kws.length;

  const [phraseRes, fullRes, partialRes] = await Promise.all([
    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         300 AS base_score
       FROM tasks t
       JOIN roles r ON t.min_role_id = r.id
       WHERE lower(t.task_description) LIKE '%' || lower(?1) || '%'
         AND t.out_of_scope IS NULL
       LIMIT 5`
    ).bind(q).all(),

    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         COUNT(DISTINCT ts.keyword) * 20 AS base_score
       FROM task_search ts
       JOIN tasks t ON ts.task_id = t.id
       JOIN roles r ON t.min_role_id = r.id
       WHERE ts.keyword IN (${ph})
         AND t.out_of_scope IS NULL
       GROUP BY t.id
       HAVING COUNT(DISTINCT ts.keyword) = ${count}
       ORDER BY base_score DESC
       LIMIT 5`
    ).bind(...kws).all(),

    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         SUM(ts.weight) AS base_score
       FROM task_search ts
       JOIN tasks t ON ts.task_id = t.id
       JOIN roles r ON t.min_role_id = r.id
       WHERE ts.keyword IN (${ph})
         AND t.out_of_scope IS NULL
       GROUP BY t.id
       ORDER BY base_score DESC
       LIMIT 10`
    ).bind(...kws).all(),
  ]);

  const merged = new Map<string, Entry>();
  const add = (rows: Record<string, unknown>[], matchType: MatchType) => {
    for (const row of rows) {
      const id    = row.id as string;
      const score = (row.base_score as number) ?? 0;
      const existing = merged.get(id);
      if (!existing || score > ((existing.row.base_score as number) ?? 0)) {
        merged.set(id, { row, matchType });
      }
    }
  };

  add((phraseRes.results  ?? []) as Record<string, unknown>[], "exact");
  add((fullRes.results    ?? []) as Record<string, unknown>[], "full_keyword");
  add((partialRes.results ?? []) as Record<string, unknown>[], "partial");

  return merged;
}

// ── BM25 ranking tier ─────────────────────────────────────────────────────
// Smoothed Okapi BM25 (k1=1.2, b=0.5).
// b reduced from standard 0.75 because corpus has short docs (avg ~6 tokens).
const BM25_K1 = 1.2;
const BM25_B  = 0.5;

async function runBM25Tier(
  env: Env,
  kws: string[],
): Promise<Map<string, Entry>> {
  if (kws.length === 0) return new Map();

  const corpus = await getCorpusStats(env);
  const avgdl  = corpus.avg_doc_length;
  const k1     = BM25_K1;
  const b      = BM25_B;

  const ph = kws.map(() => "?").join(",");

  // Per-task sum of per-keyword BM25 contributions * 100 keeps base_score
  // magnitude comparable to existing tiers after privilegeFactor multiplies.
  const sql = `
    SELECT t.id, t.task_description, t.feature_area,
           t.alt_role_ids, t.source_url,
           r.id AS min_role_id, r.display_name AS min_role_name,
           r.is_privileged, r.permissions,
           SUM(
             ts.idf *
             (ts.tf * (${k1} + 1)) /
             (ts.tf + ${k1} * (1 - ${b} + ${b} * COALESCE(t.doc_length, ${avgdl}) / ${avgdl}))
           ) * 100 AS base_score
    FROM task_search ts
    JOIN tasks t ON ts.task_id = t.id
    JOIN roles r ON t.min_role_id = r.id
    WHERE ts.keyword IN (${ph})
      AND ts.idf IS NOT NULL
      AND t.out_of_scope IS NULL
    GROUP BY t.id
    ORDER BY base_score DESC
    LIMIT 20
  `;

  const result = await env.DB.prepare(sql).bind(...kws).all();

  const map = new Map<string, Entry>();
  for (const row of (result.results ?? []) as Record<string, unknown>[]) {
    map.set(String(row.id), { row, matchType: "bm25" });
  }
  return map;
}

// LIKE-only fallback — uses longest meaningful topic keyword (≥5 chars),
// falling back to the full query phrase if none qualifies.
// This prevents short generic words like "access" from matching unrelated tasks.
async function runLikeTier(
  env: Env,
  q: string,
  keywords: string[],
  topicKeywords: string[],
): Promise<Map<string, Entry>> {
  const meaningfulTopic = topicKeywords
    .filter((k) => k.length >= 5)
    .sort((a, b) => b.length - a.length);
  const likeKw = meaningfulTopic[0] ?? q;

  const res = await env.DB.prepare(
    `SELECT t.id, t.task_description, t.feature_area,
       t.alt_role_ids, t.source_url,
       r.id AS min_role_id, r.display_name AS min_role_name,
       r.is_privileged, r.permissions,
       1 AS base_score
     FROM tasks t
     JOIN roles r ON t.min_role_id = r.id
     WHERE (lower(t.task_description) LIKE '%' || lower(?1) || '%'
        OR lower(t.feature_area)     LIKE '%' || lower(?1) || '%')
       AND t.out_of_scope IS NULL
     LIMIT 10`
  ).bind(likeKw).all();

  const merged = new Map<string, Entry>();
  for (const row of (res.results ?? []) as Record<string, unknown>[]) {
    merged.set(row.id as string, { row, matchType: "partial" });
  }
  return merged;
}

function applyAffinityAndScore(seen: Map<string, Entry>): unknown[] {
  if (seen.size === 0) return [];
  const scored = [...seen.values()].map(({ row, matchType }) => {
    const permCount = safeParseJson(row.permissions as string, []).length;
    const isPriv    = row.is_privileged === 1;
    const baseScore = (row.base_score as number) ?? 0;
    return {
      task:             row.task_description,
      feature_area:     row.feature_area as string,
      min_role:         row.min_role_name,
      min_role_id:      row.min_role_id,
      alt_roles:        safeParseJson(row.alt_role_ids as string, []),
      source_url:       row.source_url,
      is_privileged:    isPriv,
      permission_count: permCount,
      match_type:       matchType,
      score:            baseScore * privilegeFactor(permCount, isPriv),
      _permCount:       permCount,
    };
  });

  // First sort determines dominant feature area
  scored.sort((a, b) =>
    b.score !== a.score ? b.score - a.score : a._permCount - b._permCount
  );

  const dominantArea = scored[0].feature_area;
  for (const r of scored) {
    r.score = r.score * affinityFactor(r.feature_area, dominantArea);
  }

  // Re-sort after affinity
  scored.sort((a, b) =>
    b.score !== a.score ? b.score - a.score : a._permCount - b._permCount
  );

  // Minimum threshold 5%
  const topScore  = scored[0].score;
  const threshold = topScore * 0.05;

  // Explicit deduplication by task description — safety guard so the same
  // task can never appear twice regardless of how tiers merged
  const taskSeen = new Set<string>();
  return scored
    .filter((r) => {
      if (r.score < threshold) return false;
      const key = String(r.task ?? "");
      if (taskSeen.has(key)) return false;
      taskSeen.add(key);
      return true;
    })
    .slice(0, 10)
    .map(({ _permCount: _p, ...rest }) => rest);
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

function extractKeywordsForSearch(q: string): {
  keywords: string[];
  topicKeywords: string[];
  sqKeywords: string[];
} {
  const keywords      = extractKeywords(q);
  const topicKeywords = keywords.filter((k) => !GENERIC_VERBS.has(k));
  const sqKeywords    = topicKeywords.length > 0 ? topicKeywords : keywords;
  return { keywords, topicKeywords, sqKeywords };
}

async function handleSearchCompare(
  env: Env,
  q: string,
): Promise<Response> {
  const { keywords, topicKeywords, sqKeywords } = extractKeywordsForSearch(q);

  const [keywordMap, bm25Map] = await Promise.all([
    runKeywordTier(env, q, sqKeywords),
    runBM25Tier(env, sqKeywords),
  ]);

  const keywordResults = applyAffinityAndScore(keywordMap) as any[];
  const bm25Results    = applyAffinityAndScore(bm25Map)    as any[];

  return json({
    query:          q,
    keywords,
    topic_keywords: topicKeywords,
    keyword_ranker: {
      count: keywordResults.length,
      top_5: keywordResults.slice(0, 5).map((r) => ({
        task:       r.task,
        min_role:   r.min_role,
        score:      r.score,
        match_type: r.match_type,
      })),
    },
    bm25_ranker: {
      count: bm25Results.length,
      top_5: bm25Results.slice(0, 5).map((r) => ({
        task:       r.task,
        min_role:   r.min_role,
        score:      r.score,
        match_type: r.match_type,
      })),
    },
    same_top_role:
      keywordResults[0]?.min_role != null &&
      keywordResults[0]?.min_role === bm25Results[0]?.min_role,
  });
}

async function handleSearch(url: URL, env: Env): Promise<Response> {
  const q = url.searchParams.get("q")?.trim() ?? "";
  if (!q) return badRequest("Missing or empty query parameter: q");

  // Internal A/B endpoint — not part of normal search flow.
  if (url.searchParams.get("debug") === "compare") {
    return handleSearchCompare(env, q);
  }

  const { keywords, topicKeywords, sqKeywords } = extractKeywordsForSearch(q);
  if (keywords.length === 0) return json([]);

  // Tier 1: topic keywords only (precise, avoids "configure" noise)
  const tier1 = await runKeywordTier(env, q, sqKeywords);
  if (tier1.size > 0) return json(applyAffinityAndScore(tier1));

  // Tier 2: all keywords including generic verbs (only if some were stripped)
  if (topicKeywords.length < keywords.length) {
    const tier2 = await runKeywordTier(env, q, keywords);
    if (tier2.size > 0) return json(applyAffinityAndScore(tier2));
  }

  // Tier 3: LIKE fallback on longest topic/overall keyword
  const tier3 = await runLikeTier(env, q, keywords, topicKeywords);
  if (tier3.size > 0) return json(applyAffinityAndScore(tier3));

  return json([]);
}

async function handleRole(roleId: string, env: Env): Promise<Response> {
  const row = await env.DB.prepare(
    `SELECT id, display_name, description, is_privileged, is_built_in,
            permissions, first_seen, last_updated
     FROM roles WHERE id = ?`
  )
    .bind(roleId)
    .first();

  if (!row) return notFound(`Role not found: ${roleId}`);

  return json({
    id: row.id,
    displayName: row.display_name,
    description: row.description,
    isPrivileged: row.is_privileged === 1,
    isBuiltIn: row.is_built_in === 1,
    permissions: safeParseJson(row.permissions as string, []),
    firstSeen: row.first_seen,
    lastUpdated: row.last_updated,
  });
}

async function handleDiff(url: URL, env: Env): Promise<Response> {
  const a = url.searchParams.get("a")?.trim() ?? "";
  const b = url.searchParams.get("b")?.trim() ?? "";
  if (!a || !b) return badRequest("Missing params: a and b (role display names)");

  const [rowA, rowB] = await Promise.all([
    env.DB.prepare(
      "SELECT id, display_name, permissions, first_seen FROM roles WHERE lower(display_name) = lower(?)"
    )
      .bind(a)
      .first(),
    env.DB.prepare(
      "SELECT id, display_name, permissions, first_seen FROM roles WHERE lower(display_name) = lower(?)"
    )
      .bind(b)
      .first(),
  ]);

  if (!rowA) return notFound(`Role not found: ${a}`);
  if (!rowB) return notFound(`Role not found: ${b}`);

  const permsA = new Set<string>(safeParseJson(rowA.permissions as string, []));
  const permsB = new Set<string>(safeParseJson(rowB.permissions as string, []));

  const onlyInA = [...permsA].filter((p) => !permsB.has(p)).sort();
  const onlyInB = [...permsB].filter((p) => !permsA.has(p)).sort();
  const shared  = [...permsA].filter((p) =>  permsB.has(p)).sort();

  return json({
    role_a: {
      id: rowA.id,
      display_name: rowA.display_name,
      permission_count: permsA.size,
      first_seen: rowA.first_seen ?? null,
    },
    role_b: {
      id: rowB.id,
      display_name: rowB.display_name,
      permission_count: permsB.size,
      first_seen: rowB.first_seen ?? null,
    },
    only_in_a: onlyInA,
    only_in_b: onlyInB,
    shared,
  });
}

async function handleRoles(env: Env): Promise<Response> {
  const result = await env.DB.prepare(
    `SELECT id, display_name, is_privileged
     FROM roles
     WHERE is_built_in = 1
     ORDER BY display_name ASC`
  ).all();

  return json(
    (result.results ?? []).map((r) => ({
      id: r.id,
      display_name: r.display_name,
      is_privileged: r.is_privileged === 1,
    }))
  );
}

async function handleStatus(env: Env): Promise<Response> {
  const value = await env.KV.get("pipeline_status");
  if (value === null) {
    return new Response(JSON.stringify({ error: "Pipeline status unavailable" }), {
      status: 503,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
      },
    });
  }
  return new Response(value, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store",
    },
  });
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function safeParseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return corsOptions();

    const url  = new URL(request.url);
    const path = url.pathname;

    if (path === "/api/status") return handleStatus(env);
    if (path === "/api/roles")  return handleRoles(env);
    if (path === "/api/search") return handleSearch(url, env);
    if (path === "/api/diff")   return handleDiff(url, env);

    const roleMatch = path.match(/^\/api\/role\/([^/]+)$/);
    if (roleMatch) return handleRole(decodeURIComponent(roleMatch[1]), env);

    return json({ error: "Not found" }, 404);
  },
};

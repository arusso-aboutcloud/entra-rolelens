export interface Env {
  DB: D1Database;
  KV: KVNamespace;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STOP_WORDS = new Set([
  "a", "an", "the", "to", "for", "of", "in", "and", "or", "with", "how",
  "can", "i", "my", "is", "are", "do", "does", "what", "which", "who",
]);

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
// Route handlers
// ---------------------------------------------------------------------------

async function handleSearch(
  url: URL,
  env: Env
): Promise<Response> {
  const q = url.searchParams.get("q")?.trim() ?? "";
  if (!q) return badRequest("Missing or empty query parameter: q");

  const keywords = extractKeywords(q);
  if (keywords.length === 0) return json([]);

  const placeholders = keywords.map(() => "?").join(", ");
  const kwCount = keywords.length;

  // Three parallel queries: phrase match, all-keywords, partial-keywords
  const [phraseResult, fullKwResult, partialResult] = await Promise.all([

    // Q1: exact phrase match in task description (highest base score)
    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         300 AS base_score
       FROM tasks t
       JOIN roles r ON t.min_role_id = r.id
       WHERE lower(t.task_description) LIKE '%' || lower(?1) || '%'
       LIMIT 5`
    ).bind(q).all(),

    // Q2: all keywords present (AND semantics)
    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         COUNT(DISTINCT ts.keyword) * 20 AS base_score
       FROM task_search ts
       JOIN tasks t ON ts.task_id = t.id
       JOIN roles r ON t.min_role_id = r.id
       WHERE ts.keyword IN (${placeholders})
       GROUP BY t.id
       HAVING COUNT(DISTINCT ts.keyword) = ${kwCount}
       ORDER BY base_score DESC
       LIMIT 5`
    ).bind(...keywords).all(),

    // Q3: partial keyword match (OR semantics, existing behaviour)
    env.DB.prepare(
      `SELECT t.id, t.task_description, t.feature_area,
         t.alt_role_ids, t.source_url,
         r.id AS min_role_id, r.display_name AS min_role_name,
         r.is_privileged, r.permissions,
         SUM(ts.weight) AS base_score
       FROM task_search ts
       JOIN tasks t ON ts.task_id = t.id
       JOIN roles r ON t.min_role_id = r.id
       WHERE ts.keyword IN (${placeholders})
       GROUP BY t.id
       ORDER BY base_score DESC
       LIMIT 10`
    ).bind(...keywords).all(),
  ]);

  // Merge all three result sets, deduplicate by task id keeping highest base_score
  type MatchType = "exact" | "full_keyword" | "partial";
  type Entry = { row: Record<string, unknown>; matchType: MatchType };

  const seen = new Map<string, Entry>();

  const addRows = (rows: Record<string, unknown>[], matchType: MatchType) => {
    for (const row of rows) {
      const id = row.id as string;
      const score = (row.base_score as number) ?? 0;
      const existing = seen.get(id);
      if (!existing || score > ((existing.row.base_score as number) ?? 0)) {
        seen.set(id, { row, matchType });
      }
    }
  };

  addRows((phraseResult.results  ?? []) as Record<string, unknown>[], "exact");
  addRows((fullKwResult.results  ?? []) as Record<string, unknown>[], "full_keyword");
  addRows((partialResult.results ?? []) as Record<string, unknown>[], "partial");

  // Apply privilege factor and compute final score
  const scored = [...seen.values()].map(({ row, matchType }) => {
    const permCount = safeParseJson(row.permissions as string, []).length;
    const isPriv    = row.is_privileged === 1;
    const baseScore = (row.base_score as number) ?? 0;
    const factor    = privilegeFactor(permCount, isPriv);
    return {
      task:             row.task_description,
      feature_area:     row.feature_area,
      min_role:         row.min_role_name,
      min_role_id:      row.min_role_id,
      alt_roles:        safeParseJson(row.alt_role_ids as string, []),
      source_url:       row.source_url,
      is_privileged:    isPriv,
      permission_count: permCount,
      match_type:       matchType,
      score:            baseScore * factor,
      _permCount:       permCount,
    };
  });

  // Primary: score DESC; secondary: permission_count ASC (least privilege wins ties)
  scored.sort((a, b) =>
    b.score !== a.score ? b.score - a.score : a._permCount - b._permCount
  );

  const top10 = scored.slice(0, 10).map(({ _permCount: _p, ...rest }) => rest);
  return json(top10);
}

async function handleRole(
  roleId: string,
  env: Env
): Promise<Response> {
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

async function handleDiff(
  url: URL,
  env: Env
): Promise<Response> {
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

  const rows = (result.results ?? []).map((r) => ({
    id: r.id,
    display_name: r.display_name,
    is_privileged: r.is_privileged === 1,
  }));

  return json(rows);
}

async function handleStatus(env: Env): Promise<Response> {
  const value = await env.KV.get("pipeline_status");
  if (value === null) {
    return new Response(
      JSON.stringify({ error: "Pipeline status unavailable" }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "no-store",
        },
      }
    );
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

    const url = new URL(request.url);
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

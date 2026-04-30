# Extracted 220 synonym entries from index.html
import re

SYNONYMS: dict[str, str] = {
    # Short abbreviations that need synonym to bypass length gate
    'ai':                           'ai administrator',

    # Identity & access
    'pim':                          'privileged identity management',
    'privileged identity':          'privileged identity management',
    'jit':                          'just in time access',
    'just-in-time':                 'just in time access',
    'rbac':                         'role based access control',
    'role based access':            'role based access control',
    'pac':                          'privileged access',
    'pag':                          'privileged access group',

    # Authentication
    'mfa':                          'multi factor authentication',
    'multi-factor':                 'multi factor authentication',
    'multifactor':                  'multi factor authentication',
    '2fa':                          'two factor authentication',
    'two-factor':                   'two factor authentication',
    'fido2':                        'passkey passwordless authentication',
    'fido':                         'passkey passwordless authentication',
    'passkey':                      'passwordless authentication',
    'passwordless':                 'passwordless authentication',
    'sspr':                         'self service password reset',
    'self-service password':        'self service password reset',
    'password reset':               'reset user password',
    'reset password':              'reset non admin password',
    'reset user password':          'reset non admin password',
    'tap':                          'temporary access pass',
    'temporary access pass':        'temporary access pass',
    'windows hello':                'passwordless authentication',

    # Conditional Access & network
    'ca':                           'conditional access',
    'conditional access':           'conditional access',
    'cap':                          'conditional access policy',
    'named location':               'named locations conditional access',
    'trusted location':             'named locations conditional access',
    'ip range':                     'named locations conditional access',
    'gsa':                          'global secure access',
    'global secure access':         'global secure access',
    'entra internet access':        'global secure access',
    'entra private access':         'global secure access',
    'ztna':                         'zero trust network access',
    'zero trust network':           'zero trust network access',

    # External identities & guests
    'b2b':                          'external collaboration guest users',
    'b2c':                          'external identities',
    'guest':                        'guest users external collaboration',
    'external user':                'guest users external collaboration',
    'external identity':            'external identities',
    'cross-tenant':                 'cross tenant access',
    'cross tenant':                 'cross tenant access',

    # Applications & service principals
    'app registration':             'application registration',
    'app registrations':            'application registration',
    'app reg':                      'application registration',
    'service principal':            'enterprise application service principal',
    'sp':                           'service principal enterprise application',
    'enterprise app':               'enterprise application',
    'saml':                         'enterprise application single sign on',
    'sso':                          'single sign on enterprise application',
    'single sign-on':               'single sign on enterprise application',
    'oauth':                        'application permission oauth',
    'api permission':               'application permission consent',
    'admin consent':                'application permission consent grant',

    # Entitlement management & governance
    'elm':                          'entitlement management',
    'entitlement':                  'entitlement management access package',
    'access package':               'entitlement management access package',
    'access packages':              'entitlement management access package',
    'manage access packages':       'entitlement management access package',
    'access review':                'access reviews',
    'lifecycle':                    'lifecycle workflows identity governance',
    'identity governance':          'entitlement management access reviews',

    # Devices
    'mdm':                          'mobile device management',
    'device management':            'mobile device management intune',
    'intune':                       'mobile device management',
    'aad join':                     'azure ad join device',
    'entra join':                   'azure ad join device',
    'hybrid join':                  'hybrid azure ad joined device',
    'bitlocker':                    'bitlocker device encryption',
    'compliance policy':            'device compliance intune',

    # Security & monitoring
    'defender':                     'microsoft defender security',
    'identity protection':          'microsoft entra id protection risk',
    'id protection':                'microsoft entra id protection risk',
    'risky user':                   'identity protection risk user',
    'risky sign-in':                'identity protection risk sign in',
    'sign in log':                  'sign in logs audit',
    'signin log':                   'sign in logs audit',
    'audit log':                    'audit logs monitoring',
    'diagnostic':                   'diagnostic settings monitoring',
    'siem':                         'security information event management',

    # Directory & users
    'aad':                          'azure active directory',
    'azure ad':                     'microsoft entra id',
    'entra id':                     'microsoft entra id',
    'directory role':               'directory role assignment',
    'admin unit':                   'administrative unit',
    'administrative unit':          'administrative unit',
    'administrative units':         'administrative unit',
    'manage administrative units':  'administrative unit',
    'scoped admin':                 'administrative unit',
    'au':                           'administrative unit',
    'bulk user':                    'bulk create import users',
    'manage groups':                'group membership management',
    'dynamic group':                'dynamic membership group',
    'dynamic membership':           'dynamic membership group',
    'license':                      'license assignment',
    'license assignment':           'license assignment',

    # Networking & hybrid
    'ad connect':                   'azure ad connect hybrid',
    'azure ad connect':             'azure ad connect hybrid sync',
    'adc':                          'azure ad connect',
    'hybrid':                       'hybrid azure ad connect on premises',
    'on-premises':                  'on premises directory sync',
    'on prem':                      'on premises directory sync',
    'password hash sync':           'password hash synchronization azure ad connect',
    'phs':                          'password hash synchronization',
    'pts':                          'pass through authentication',
    'pass-through':                 'pass through authentication',
    'pta':                          'pass through authentication',
    'federation':                   'federated identity federation',
    'adfs':                         'active directory federation services',

    # Misc Entra features
    'verified id':                  'verifiable credentials',
    'verifiable credential':        'verifiable credentials',
    'workload identity':            'workload identity federated credential',
    'managed identity':             'managed identity workload',
    'custom domain':                'custom domain name dns',
    'tenant':                       'tenant settings configuration',
    'terms of use':                 'terms of use compliance',
    'tou':                          'terms of use',

    # Agent identity
    'manage ai agents':             'agent identity',
    'ai agent management':          'agent identity',
    'agent management':             'agent identity',
    'ai agent':                     'agent identity',
    'copilot agent':                'agent identity',
    'bot identity':                 'agent identity',
    'bot':                          'agent identity',
    'nhi':                          'agent identity',
    'non-human identity':           'agent identity',
    'nonhuman identity':            'agent identity',
    'machine identity':             'agent identity',
    'agentic identity':             'agent identity',
    'genai identity':               'agent identity',
    'llm agent':                    'agent identity',
    'autonomous agent':             'agent identity',
    'blueprint':                    'agent identity blueprint',
    'agent blueprint':              'agent identity blueprint',
    'agent id':                     'agent identity',
    'sponsor':                      'agent sponsor',
    'agent owner':                  'agent sponsor',
    'agent registry':               'agent registry administrator',
    'agent rbac':                   'agent id administrator',
    'govern agents':                'agent id administrator',
    'service account':              'service principal',
    'svc account':                  'service principal',
    'robot account':                'service principal',
    'nhi governance':               'nonhuman identity',
    'orphaned agent':               'agent identity',
    'ownerless agent':              'agent identity',
    'hybrid identity admin':        'entra connect administrator',
    'entra connect admin':          'entra connect administrator',
    'passkey admin':                'authentication administrator',
    'fido admin':                   'authentication administrator',
    'external user admin':          'guest inviter',
    'guest admin':                  'guest inviter',
    'pim for groups':               'privileged access administrator',
    'privileged access group':      'privileged access administrator',
    'eligible group member':        'privileged identity management',

    # AI governance
    'copilot admin':                'ai administrator',
    'copilot rbac':                 'ai administrator',
    'ai rbac':                      'ai administrator',
    'copilot permissions':          'ai administrator',
    'copilot governance':           'copilot governance',
    'm365 copilot admin':           'ai administrator',
    'ai audit':                     'ai reader',
    'copilot audit':                'ai reader',
    'ai read-only':                 'ai reader',
    'genai admin':                  'ai administrator',
    'llm admin':                    'ai administrator',
    'copilot':                      'ai administrator',
    'm365 copilot':                 'ai administrator',
    'ai governance':                'ai administrator',
    'ai admin':                     'ai administrator',
    'openai admin':                 'ai administrator',
    'chatgpt admin':                'ai administrator',
    'ai reader':                    'ai reader',
    'govern copilot':               'ai administrator',

    # Backup and recovery
    'backup':                       'entra backup administrator',
    'entra backup':                 'entra backup administrator',
    'tenant backup':                'entra backup administrator',
    'directory backup':             'entra backup administrator',
    'entra restore':                'entra backup administrator',
    'tenant restore':               'entra backup administrator',
    'disaster recovery':            'entra backup administrator',
    'dr':                           'entra backup administrator',
    'bcdr':                         'entra backup administrator',
    'recover deleted':              'entra backup administrator',
    'undelete':                     'entra backup administrator',
    'rollback':                     'entra backup administrator',
    'recovery':                     'entra backup administrator',
    'backup admin':                 'entra backup administrator',
    'entra dr':                     'entra backup administrator',
    'restore entra':                'entra backup administrator',
    'recover deleted users':        'entra backup administrator',
    'recover deleted groups':       'entra backup administrator',

    # GDAP and tenant governance
    'gdap relationships':           'gdap relationships partners',
    'gdap':                         'tenant governance administrator',
    'granular delegated admin':     'tenant governance administrator',
    'csp admin':                    'tenant governance administrator',
    'msp admin':                    'tenant governance administrator',
    'partner access':               'tenant governance administrator',
    'delegated admin':              'tenant governance administrator',
    'dap':                          'tenant governance administrator',
    'customer tenant':              'tenant governance administrator',
    'managing customer tenants':    'tenant governance administrator',
    'gdap relationship':            'tenant governance relationship administrator',
    'csp':                          'tenant governance',
    'partner delegation':           'tenant governance',

    # Shadow / unlisted roles
    'hidden roles':                 'shadow role',
    'undocumented roles':           'shadow role',
    'new roles':                    'shadow role',
    'secret roles':                 'shadow role',
    'stealth roles':                'shadow role',
    'graph only':                   'shadow role',
    'missing from docs':            'shadow role',
    'not in docs':                  'shadow role',
    'unlisted roles':               'shadow role',
    'unlisted':                     'shadow role',

    # Agent assignability
    'role for agent':               'agent assignable',
    'agent compatible':             'agent assignable',
    'agent restrictions':           'agent blocked roles',
    'blocked for agents':           'agent blocked roles',
}

# Words that appear inside multiple synonym expansion values but should NOT
# independently route queries. Without this guard, common words like "users"
# get reverse-indexed back to the first expansion containing them, causing
# unrelated queries to be hijacked.
#
# Keep this list in sync with the equivalent STOPWORDS set in
# frontend/index.html (Chunk 4, 2026-04-25).
_REVERSE_MAP_STOPWORDS = {
    "access", "account", "accounts", "active", "all", "and", "any",
    "application", "applications", "audit", "based", "between", "block",
    "can", "cloud", "configuration", "connect", "create", "data",
    "device", "devices", "directory", "domain", "edit", "entra", "every",
    "factor", "for", "from", "group", "groups", "id", "identities",
    "identity", "in", "information", "into", "issue", "key", "list",
    "log", "logs", "manage", "management", "method", "methods",
    "microsoft", "mobile", "monitoring", "name", "new", "not", "of",
    "on", "or", "out", "own", "policy", "premises", "principal",
    "register", "registration", "reset", "review", "reviews", "role",
    "roles", "secure", "security", "service", "services", "set",
    "settings", "shadow", "sign", "single", "tenant", "the", "through",
    "time", "to", "trust", "two", "use", "user", "users", "via", "with",
    "workload", "zero",
}


def _build_reverse_map(synonyms: dict) -> dict:
    """Mirror the JS REVERSE_SYNONYMS IIFE.

    Indexes synonym keys back to their expansions, plus each word in every
    expansion value (length >= 3) that is NOT in _REVERSE_MAP_STOPWORDS.
    The stopword guard prevents common English words from hijacking queries
    via Step 3 of expand_query.
    """
    mapping = {}
    for key, expansion in synonyms.items():
        lower_key = key.lower()
        if lower_key not in mapping:
            mapping[lower_key] = expansion
        for word in expansion.split():
            lw = word.lower()
            if (
                len(word) >= 3
                and lw not in mapping
                and lw not in _REVERSE_MAP_STOPWORDS
            ):
                mapping[lw] = expansion
    return mapping


_REVERSE_SYNONYMS: dict[str, str] = _build_reverse_map(SYNONYMS)


def expand_query(input_query: str) -> str:
    """Mirror of the JS expandQuery() in index.html."""
    lower = input_query.lower().strip()

    # 1. Exact key match
    if lower in SYNONYMS:
        return SYNONYMS[lower]

    # 2. Key contained within input (whole-word boundary match)
    for key, expansion in SYNONYMS.items():
        pattern = re.compile(
            r'\b' + re.escape(key) + r'\b',
            re.IGNORECASE,
        )
        if pattern.search(lower):
            return pattern.sub(expansion, lower)

    # 3. Any word in the input matches a reverse-synonym
    for word in lower.split():
        if word in _REVERSE_SYNONYMS:
            return _REVERSE_SYNONYMS[word]

    # 4. No match — return original
    return input_query

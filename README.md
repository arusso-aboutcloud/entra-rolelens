<div align="center">

![Entra RoleLens](assets/project-banner.png)

# Entra RoleLens

[![Live](https://img.shields.io/website?url=https%3A%2F%2Fentrarolelens.aboutcloud.io&label=live&style=flat-square&color=00E5A3)](https://entrarolelens.aboutcloud.io)
[![Pipeline](https://img.shields.io/github/actions/workflow/status/arusso-aboutcloud/entra-rolelens/refresh.yml?label=nightly%20pipeline&style=flat-square&branch=master&color=00E5A3)](https://github.com/arusso-aboutcloud/entra-rolelens/actions)
[![Last commit](https://img.shields.io/github/last-commit/arusso-aboutcloud/entra-rolelens/master?style=flat-square&color=00E5A3)](https://github.com/arusso-aboutcloud/entra-rolelens/commits/master)
[![License](https://img.shields.io/badge/license-MIT-38BDF8?style=flat-square)](LICENSE)
[![Roles](https://img.shields.io/badge/roles-130%2B-0078D4?style=flat-square&logo=microsoft)](https://entrarolelens.aboutcloud.io)
[![Tasks](https://img.shields.io/badge/tasks-211-0078D4?style=flat-square&logo=microsoft)](https://entrarolelens.aboutcloud.io)

**[entrarolelens.aboutcloud.io](https://entrarolelens.aboutcloud.io)** · [Report a mapping error](https://github.com/arusso-aboutcloud/entra-rolelens/issues) · [Request a task](https://github.com/arusso-aboutcloud/entra-rolelens/issues)

</div>

---

## What is Entra RoleLens?

You describe a task — *"reset a user's MFA"*, *"read audit logs"*, *"manage Conditional Access policies"* — and Entra RoleLens returns the minimum built-in Entra ID role required to do it, and nothing more.

**It replaces the 50-tab Microsoft docs crawl with a professional-grade validator that cross-references live API data with official documentation.**

---

## Features

| Mode | What it does |
|------|-------------|
| **Task → Role** | Describe what you need to do in plain language. Get back the minimum built-in role and a privilege warning if the role is elevated. |
| **Role Diff** | Select any two built-in roles. See every permission one has that the other lacks in a clean three-column view. |
| **Shadow Detection** | The integration detects "Shadow Roles" — roles that exist in Entra ID but are not yet present in the public documentation. |
| **Always current** | Refreshes nightly via a secure, passwordless pipeline. Every change Microsoft makes is detected, logged, and live by morning. |

---

## Architecture & Security

Entra RoleLens is powered by a **Zero-Trust automated pipeline**. We utilize two distinct layers to visualize the system and its security protocols.

### 1. System Overview
The high-level architecture utilizes a serverless stack on Cloudflare to provide sub-5ms response times.

[![Architecture](assets/architecture.svg)](assets/architecture.svg)

### 2. Secure Passwordless Pipeline (OIDC)
Instead of using vulnerable static secrets, we use **Workload Identity Federation (Federated Credentials)** to securely connect GitHub Actions to Microsoft Entra ID.

[![Pipeline Auth](assets/pipeline-auth.svg)](assets/pipeline-auth.svg)

**How the Handshake Works:**
1. **OIDC Handshake**: GitHub Actions requests a short-lived JWT from GitHub's OIDC provider.
2. **Trust Validation**: Microsoft Entra ID validates the JWT against a **Federated Credential** (tied specifically to the `master` branch of this repository).
3. **Passwordless Access**: Entra ID issues a temporary access token. The pipeline uses this to query the **Microsoft Graph API** without any stored passwords or keys.

---

## Technical stack

| Layer | Technology | Cost |
|-------|-----------|------|
| Frontend | Cloudflare Pages · Global CDN | €0 |
| API | Cloudflare Workers · TypeScript | €0 |
| Database | Cloudflare D1 · SQLite | €0 |
| Cache | Cloudflare KV · master.json | €0 |
| **Auth** | **Entra ID · Federated Credentials (OIDC)** | **€0** |
| Pipeline | GitHub Actions · Python 3.11 | €0 |
| **Total** | | **€0 / month** |

---

## How it stays accurate — the self-sustaining pipeline

Every night at **01:00 UTC**, a GitHub Actions workflow runs automatically:

01:00 UTC — GitHub Actions wakes up
│
├── OIDC Auth           Establishes a passwordless trust with Entra ID
│
├── fetch_roles.py      Pulls definitions from live Microsoft Graph API and docs
│
├── scrape_tasks.py     Parses 211 task → minimum role mappings from Microsoft Learn
│
├── diff_roles.py       Detects ADDED, REMOVED, or MODIFIED roles/permissions
│
├── enrich.py           Merges live API data with human-readable documentation
│
└── push_to_cloudflare.py
Updates the global cache (KV) and SQLite database (D1)


---

## Data sources

| Source | URL | Used for |
|--------|-----|----------|
| **Microsoft Graph** | `graph.microsoft.com/v1.0` | **Live Source of Truth (OIDC Authenticated)** |
| Entra-docs | `github.com/MicrosoftDocs/entra-docs` | Human-readable role descriptions and metadata |
| Microsoft Learn | `learn.microsoft.com/.../delegate-by-task` | Task → minimum role mappings |

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">
  <sub>Built on Microsoft's public data · Not affiliated with or endorsed by Microsoft</sub><br>
  <sub>Made by <a href="https://aboutcloud.io">aboutcloud.io</a> ·
  <a href="https://www.linkedin.com/in/antonio-russo-9295731b/">Antonio Russo</a></sub>
</div>

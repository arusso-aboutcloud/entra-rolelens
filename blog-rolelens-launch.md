---
title: I built a free Entra ID minimum privilege finder — here is how and why
slug: entra-rolelens-minimum-privilege-tool
tags: Entra ID, Security, Zero Trust, Community Tools, Cloudflare
feature_image: assets/banner.svg
published: true
---

## The problem every Entra admin knows

Someone on the helpdesk needs to reset MFA for a user. Simple enough task. But the manager asks: "what role should I assign so they can do that without getting too much access?"

You open Microsoft Learn. You open the built-in roles reference. You navigate to the least-privileged-by-task page, which is long, only partially searchable, and covers maybe a third of the tasks you actually need to do. You cross-reference two or three role descriptions. Twenty minutes later you have an answer you are not fully confident in, and you know you will have to do this again next week for a slightly different task.

This happens constantly. Not because Entra admins do not know their environment — they do. It happens because the Microsoft documentation is comprehensive but not queryable. There is no "I want to do X, give me the minimum role" interface. There is a reference, and you have to work through it manually.

That is the problem Entra RoleLens solves.

## What Entra RoleLens does

The tool has two modes.

**Task → Role** is the primary one. You type a task in plain language — "reset user MFA", "read audit logs", "manage Conditional Access policies" — and the tool returns the minimum built-in Entra ID role required to perform it, with a direct link to the Microsoft Learn source. No interpretation. Just the answer and the citation.

"Reset user MFA" returns *Authentication Administrator*. "Read audit logs" returns *Reports Reader*. "Manage Conditional Access" returns *Conditional Access Administrator*. Each result flags whether the role is privileged and shows any documented alternative roles.

**Role Diff** is for when you already know two roles and want to understand what separates them. Select any two built-in roles and the tool computes a three-column comparison: permissions only in Role A, permissions shared by both, permissions only in Role B. Global Administrator carries 267 permissions. User Administrator carries 56. The diff makes it immediately clear what you are adding to scope when you go broader — useful for understanding blast radius and for justifying role choices to security teams.

Both modes pull from the same dataset: 130 built-in Entra ID roles, 211 mapped tasks, refreshed nightly.

## Why no AI

This is a deliberate design choice, and it is worth being explicit about.

The people who would use a tool like this — Entra admins, IAM engineers, security architects — are exactly the people who should not be using an LLM to make production role assignment decisions. "The model thinks this is probably Authentication Administrator" is not an acceptable answer when you are assigning roles in a tenant that controls access to production infrastructure.

Every result in Entra RoleLens comes directly from Microsoft's own published data. The task-to-role mappings are scraped from the Microsoft Learn least-privileged-by-task documentation. The role definitions come from the MicrosoftDocs/entra-docs GitHub repository. If the tool says *Authentication Administrator*, that is what Microsoft's documentation says — not what a model inferred from training data.

The deterministic engine is the trust signal. When you share a result with a security reviewer or an auditor, you can show them the source. That matters.

## How it was built — the technical bit

The entire stack runs on Cloudflare's free tier and GitHub Actions' free tier. Total recurring infrastructure cost: €0.

**Cloudflare Workers** serves the API. There are four routes: `/api/search` (keyword search against tasks), `/api/roles` (full role catalog for autocomplete), `/api/role/:id` (single role with permissions), and `/api/diff` (permission diff between two named roles).

**Cloudflare D1** is the database — SQLite at the edge. It holds a `roles` table (130 rows with the full permissions JSON), a `tasks` table (211 task-to-role mappings), and a `task_search` table with pre-extracted keywords and weights for fast matching. Queries return in under 5ms.

**Cloudflare KV** caches a `pipeline_status` JSON blob that the frontend uses for the "last updated" indicator.

**Cloudflare Pages** serves the frontend — a single `index.html` with vanilla JS, no framework.

The **data pipeline** runs on GitHub Actions at 01:00 UTC nightly. It fetches role definitions from the MicrosoftDocs/entra-docs repository, scrapes the Microsoft Learn least-privileged-by-task page, diffs today's data against yesterday's, and pushes updates to D1 and KV.

One discovery worth sharing: the Microsoft Graph API `/roleManagement/directory/roleDefinitions` endpoint returns 401 without a bearer token despite documentation suggesting otherwise. The MicrosoftDocs GitHub repository is the cleaner source — same data, no auth required, version-controlled.

The search engine is weighted keyword matching against a `task_search` table. Keywords are extracted at pipeline time and stored with weights — task title keywords score higher than feature area keywords. A query like "reset password" hits the keyword index and returns ranked results in a single SQL query. Sub-5ms. No LLM in the hot path.

## The data gap — and how you can help

211 tasks are mapped. That covers the most common administrative scenarios — user management, group management, Conditional Access, basic security operations. But Microsoft's environment is large, and the official documentation does not cover everything.

Entire product areas are thin or missing: PIM-specific operations, Entitlement Management, External Identities, some Defender for Identity integrations.

The task dataset lives in `data/tasks.json` in the public GitHub repository. The schema is straightforward: task description, feature area, minimum role ID, optional alternative roles, and a Microsoft Learn source URL.

If a task is missing, open an issue with the Microsoft Learn source link or submit a PR. Every merged contribution is live within minutes via the nightly pipeline.

The community is the quality layer.

## Try it

**[entrarolelens.aboutcloud.io](https://entrarolelens.aboutcloud.io)**

Source: [github.com/arusso-aboutcloud/entra-rolelens](https://github.com/arusso-aboutcloud/entra-rolelens)

If this saves you one 20-minute Microsoft docs crawl, it was worth building. If you find a missing task or a wrong mapping, a PR takes five minutes and helps everyone who runs into the same problem.

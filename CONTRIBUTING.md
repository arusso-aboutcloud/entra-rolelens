# Contributing to Entra RoleLens

Thank you for helping make Entra RoleLens more complete and accurate.

## Reporting a missing task

If you searched for a task and got no results, please open a GitHub Issue:

1. Click **Issues → New issue → Missing task**.
2. Fill in the task description (e.g. "configure email one-time passcode").
3. Paste the Microsoft Learn URL that documents this task.
4. Suggest the minimum Entra role required, if you know it.

Microsoft Learn is the authoritative source for all task-to-role mappings:
<https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-by-task>

---

## Submitting a task mapping via Pull Request

All task data lives in `data/tasks.json`. To add or correct a task:

1. Fork the repository and create a branch (`git checkout -b add/my-task`).
2. Edit `data/tasks.json` — append your entry to the relevant feature area array, or add a new area object.
3. Validate the JSON at <https://jsonlint.com> before committing.
4. Open a PR against `master` and fill in the PR template checklist.

### JSON structure

Each task entry follows this shape:

```json
{
  "task": "Reset user MFA",
  "min_role": "Authentication Administrator",
  "alt_roles": ["Privileged Authentication Administrator", "Global Administrator"],
  "source_url": "https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-by-task#users",
  "feature_area": "Users"
}
```

| Field | Required | Description |
|---|---|---|
| `task` | yes | Short, imperative description of the admin task |
| `min_role` | yes | Least-privileged built-in Entra role that can perform the task |
| `alt_roles` | no | Other roles that also cover this task |
| `source_url` | yes | Direct link to the Microsoft Learn section that documents this |
| `feature_area` | yes | Logical grouping (Users, Groups, Applications, …) |

---

## Review and deployment

- PRs require **one approval** from a maintainer before merging.
- Once merged to `master`, deployment to <https://entrarolelens.aboutcloud.io> is **automatic** via the GitHub Actions workflow in `.github/workflows/`.
- The nightly data refresh also runs automatically — no manual step needed for data-only changes.

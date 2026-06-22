# Descope Flow CI/CD Template

A clean, ready-to-use template for managing a Descope project with GitHub Actions.
It provides two capabilities:

1. **Flow promotion (PR-gated):** promote flows Dev → Staging → Production **without
   overwriting the target project's connectors or other settings**. Every promotion
   goes through a reviewable pull request before anything is imported.
2. **Standard snapshot CI/CD:** the original Descope template workflows for exporting
   a full project snapshot to a PR and importing it into production on merge.

> This repo ships **empty of project data** on purpose. There is no `ProjectSnapshot/`
> and no `flows/` directory yet — those are created the first time you run a workflow
> against your own Descope projects. Nothing here is tied to any specific project; the
> workflows read project IDs and keys from the repository variables/secrets below.

---

## Flow promotion (Dev → Staging → Production)

### Why this exists

Importing a single flow directly into another project breaks its connector references —
the source flow carries the *source* project's connector IDs, which don't exist in the
target, so the connector steps get deselected on import.

A **full project snapshot import** runs Descope's reference-mapping pass and rebinds
connector references correctly — but it also carries everything else (connectors,
settings, etc.) from the source, which you do **not** want to push downstream.

This pipeline imports the **target's own snapshot** with only the **flows swapped in**.
The mapping pass runs (so connector references rebind onto the target's connectors), and
nothing else in the target changes.

### The two-step, PR-gated model

**Step 1 — Open PR** (`Flows 1 — Open PR: …`, run manually): exports the chosen flows
from the source project and commits **only those flow files** into `flows/<target>/`,
then opens a pull request. The PR diff is exactly which flow definitions will change.
Nothing is imported yet.

**Step 2 — Deploy** (`Flows 2 — Deploy: …`, runs automatically on merge): when the PR
merges to `main`, this exports a fresh snapshot of the target, overlays the merged flows
from `flows/<target>/`, validates, and imports. If validation fails (broken reference /
missing secret) it aborts and imports nothing.

```
Dev ──[Flows 1: Open PR]──▶ PR (flows/staging/ diff) ──merge──▶ [Flows 2: Deploy] ──▶ Staging
Staging ──[Flows 1: Open PR]──▶ PR (flows/production/ diff) ──merge──▶ [Flows 2: Deploy] ──▶ Production
```

The tracked directories `flows/staging/` and `flows/production/` are the managed flow set
for each environment. The deploy step only **adds/updates** those flows in the target; it
never deletes other flows, and it never touches connectors.

### How secrets work

The key idea: **snapshots are "config without secrets."** When Descope exports a snapshot,
it includes the *configuration* of connectors, OAuth providers, and outbound apps (names,
URLs, auth type, etc.) but **strips out the secret values** (API keys, client secrets,
bearer tokens). Secrets are never written to an export, a git repo, or a CI log. So every
snapshot is structurally complete but has "holes" where the secret values would go.

At import time, Descope fills those holes in this order of precedence:

1. **Already present in the target → preserved.** If the connector already exists in the
   destination project with its secret set, import keeps it — it does **not** blank it
   out. This is the case that matters here: the deploy step imports the target's own
   snapshot, so every connector already exists with its secret and they all stay put. In
   the normal case you supply **no** secrets.
2. **Supplied at import time → used / overrides.** You can pass secret values via
   `inputSecrets` (API) / `--secrets-input` (CLI), for secrets that are *new* to the
   target or a deliberate rotation.
3. **Needed but absent and not supplied → flagged as missing.** `validate` returns a
   `missingSecrets` list and the deploy aborts with the exact template to fill.

#### The secrets-input format

```json
{
  "connector-<connectorId>": { "name": "My HTTP Connector", "secrets": { "bearerToken": "..." } },
  "oauthprovider-<id>":      { "name": "Google",            "secrets": { "clientSecret": "..." } },
  "outboundapp-<id>":        { "name": "My Outbound App",   "secrets": { "clientSecret": "..." } }
}
```

That JSON lives in the `STAGING_CONNECTOR_SECRETS` / `PRODUCTION_CONNECTOR_SECRETS` GitHub
secret; the deploy workflow passes it as `--secrets-input` to both `validate` and `import`.
You usually leave these empty — because the deploy re-imports the target's own snapshot,
existing secrets are preserved. Only populate them if a promoted flow introduces a
brand-new connector.

---

## One-time setup

### 1. Repository variables

`Settings → Secrets and variables → Actions → Variables`:

| Variable | Value |
| --- | --- |
| `DEV_PROJECT_ID` | Project ID of your dev project |
| `STAGING_PROJECT_ID` | Project ID of your staging project |
| `PRODUCTION_PROJECT_ID` | Project ID of your production project |
| `DESCOPE_BASE_URL` | *(optional)* only if you are not on `api.descope.com` |

### 2. Repository secrets

`Settings → Secrets and variables → Actions → Secrets`:

| Secret | Required? | Purpose |
| --- | --- | --- |
| `MANAGEMENT_KEY` | fallback | Used for any project key not set explicitly below |
| `DEV_MANAGEMENT_KEY` | optional | Management key scoped to dev |
| `STAGING_MANAGEMENT_KEY` | optional | Management key scoped to staging |
| `PRODUCTION_MANAGEMENT_KEY` | optional | Management key scoped to production |
| `STAGING_CONNECTOR_SECRETS` | optional | Connector secrets JSON for staging (see "How secrets work") |
| `PRODUCTION_CONNECTOR_SECRETS` | optional | Connector secrets JSON for production |

If one key reaches all projects, just set `MANAGEMENT_KEY`. You can find a project's ID in
[Project Settings](https://app.descope.com/settings/project) and create a management key in
[Company → Management Keys](https://app.descope.com/settings/company/managementkeys).

### 3. Let Actions open PRs

`Settings → Actions → General → Workflow permissions`: enable **Read and write permissions**
and check **Allow GitHub Actions to create and approve pull requests**.

### 4. Require review before merge (this is the approval gate)

`Settings → Branches` (ruleset or branch protection) on `main`: require a pull request and
at least one approving review before merging. This is what enforces "must be approved" — the
deploy only runs after the PR merges.

> Optional extra gate: create a `production` Environment with required reviewers and set
> `environment_name: production` in `flows-deploy-prod.yml` to also gate the import step.

---

## How to run a flow promotion

1. **Actions → Flows 1 — Open PR: Dev → Staging → Run workflow.**
   - **flows** — a single flow ID, a comma-separated list (e.g. `sign-up-or-in,reset-password`), or `all`.
2. A PR is opened against `main` with the flow diff under `flows/staging/`. Review it.
3. Approve & merge. **Flows 2 — Deploy: Staging** runs automatically and imports into staging.
4. To go to production, repeat with **Flows 1 — Open PR: Staging → Production**, review the
   `flows/production/` diff, merge, and **Flows 2 — Deploy: Production** imports into prod.

Tip: find flow IDs with `descope flow list -j` against the source project, or read them from
the `flows/<target>/` directory once it exists.

### ⚠️ Validate this before relying on it

The reference-mapping in the deploy step rebinds a promoted flow onto the target's
connectors **by matching connector names**. This works cleanly when the same connector has
the **same name** across dev / staging / production (the normal case when environments share
snapshot lineage). Before trusting this for production, do one dry run: promote a single
flow that uses a connector dev → staging, merge, then open it in the staging console and
confirm the connector step is still wired up. If `validate` reports a broken reference, the
connector names differ between environments — align them and re-run.

---

## Standard snapshot CI/CD (optional)

The original Descope template workflows are included for full-project snapshot promotion:

- **Create Pull Request from Staging Project** (`update-staging.yml`) — exports a full
  snapshot of staging into `ProjectSnapshot/` and opens a PR.
- **Deploy to Production Project** (`deploy-production.yml`) — on merge to `main`, validates
  and imports the `ProjectSnapshot/` into production.
- `create-pullreq.yml` (reusable) and `manual-pullreq.yml` (example) support the above.

Use these if you want to source-control and promote the **entire** project; use the flow
promotion workflows above when you only want to move flows and keep the target's connectors
in place.

---

## Workflows in this repo

| Workflow | Purpose |
| --- | --- |
| `flows-pr-dev-to-staging.yml` | Step 1: open a PR promoting flows dev → staging |
| `flows-pr-staging-to-prod.yml` | Step 1: open a PR promoting flows staging → production |
| `flows-deploy-staging.yml` | Step 2: import merged flows into staging |
| `flows-deploy-prod.yml` | Step 2: import merged flows into production |
| `flows-open-pr.yml` | Reusable engine for Step 1 |
| `flows-deploy.yml` | Reusable engine for Step 2 |
| `update-staging.yml` | Full-snapshot export of staging → PR |
| `deploy-production.yml` | Full-snapshot import into production on merge |
| `create-pullreq.yml` | Reusable full-snapshot export → PR |
| `manual-pullreq.yml` | Example: manual full-snapshot export |

The flow workflows use the Descope CLI directly (via `descope/descopecli`'s `install`
action) because the swap step needs to modify the `flows/` directory between export and
import. The snapshot workflows use Descope's published `export` / `import` composite actions.

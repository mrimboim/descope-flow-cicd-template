# Adding visual flow diffs to your Descope CI/CD pipeline

Every Descope environment-promotion setup ends the same way: a PR whose diff is
raw flow JSON — task graphs, craft trees, and node coordinates that no reviewer
can actually read. The `flow-diff` action turns that PR into pictures:

| Image | Shows |
|---|---|
| `00-overview` | The whole flow at its console coordinates — green added / red removed / orange modified blocks, purple dotted lines for moves, rewired connections |
| `10-cluster-*` | A zoom on each changed region with 1-hop context |
| `20-screen-*` / `21-pixel-*` | Screens rendered with **Descope's own rendering engine** (`@descope/page-editor-components`), old vs new, changed components outlined |
| `30-condition-*` / `40-action-*` / `50-connector-*` | Per-block panels: branch logic, argument values, and error handling old → new |
| `summary.md` / `diff.json` | Human changelog / machine-readable diff |

It understands **both flow formats** with zero configuration:

- **Snapshot folders** — `flows/<flow-id>/contents.json` + `metadata.json` + `screen-*.json`, as committed by [`descope/project-cicd-template`](https://github.com/descope/project-cicd-template) and `descope project snapshot export`
- **Single-file console exports** — `flows/<flow-id>.json`, as used by the [Terraform provider](https://docs.descope.com/managing-environments/terraform) (`flows = { "sign-up-or-in" = { data = file("flows/sign-up-or-in.json") } }`)

> **Why the images only show the NEW state in the PR (no old-vs-new image slider):**
> each diff is written to a folder named by content hash
> (`flow-diffs/<flow-id>/<oldhash>-<newhash>/`) and the previous folder is deleted
> in the same commit — so GitHub treats every image as *added* and renders just it.

---

## Option 1 — You use `descope/project-cicd-template` (snapshot layout)

Add the action right after the `descope/descopecli/.github/actions/export` step
in `.github/workflows/create-pullreq.yml`, and append its markdown to the PR body:

```yaml
      - name: Visual flow diffs
        id: flowdiff
        uses: mrimboim/descope-flow-cicd-template/.github/actions/flow-diff@main
        with:
          flows-path: ProjectSnapshot/flows
          output-path: flow-diffs
          image-url-prefix: https://github.com/${{ github.repository }}/raw/descope/update-snapshot

      # then include ${{ steps.flowdiff.outputs.markdown-file }} in the PR body
      # the template's create-pull-request step commits the whole tree, so the
      # flow-diffs/ images show up in Files changed automatically
```

## Option 2 — You use this template's promotion workflows

Nothing to do — `flows-open-pr.yml` already generates and commits the images.
Toggles (all default on):

```yaml
    with:
      visual_diffs: true       # generate + commit images
      inline_pr_images: true   # embed them in the PR description
      pixel_render: true       # real screen renders (Chromium; off = faster CI)
```

## Option 3 — You manage flows with the Terraform provider

Your flow JSONs are single-file console exports referenced by `file()` in
`descope_project.flows`. Diff them on every PR that touches them:

```yaml
name: Visual flow diffs
on:
  pull_request:
    paths: ['flows/**.json']

permissions:
  contents: write
  pull-requests: write

jobs:
  flow-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
          fetch-depth: 0

      - name: Visual flow diffs
        id: flowdiff
        uses: mrimboim/descope-flow-cicd-template/.github/actions/flow-diff@main
        with:
          flows-path: flows
          base-ref: ${{ github.event.pull_request.base.sha }}
          image-url-prefix: https://github.com/${{ github.repository }}/raw/${{ github.head_ref }}

      - name: Commit diff images to the PR branch
        if: steps.flowdiff.outputs.changed-count != '0'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add flow-diffs
          git diff --cached --quiet || git commit -m "flow-diff: update visual diffs"
          git push

      - name: Post/update PR comment with the images
        if: steps.flowdiff.outputs.changed-count != '0'
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          header: flow-diff
          path: ${{ steps.flowdiff.outputs.markdown-file }}
```

## Option 4 — Any other CI (GitLab, Jenkins, …)

The tool is two files with ordinary dependencies — no GitHub required:

```bash
pip install cairosvg
cd tools/flow-diff && npm install && npx playwright-core install --with-deps chromium-headless-shell

# old and new can each be a single-file export OR a snapshot flow directory
python3 tools/flow-diff/flow_diff.py old-flow/ new-flow/ -o out/
# fast mode, no node/Chromium needed:
python3 tools/flow-diff/flow_diff.py old.json new.json -o out/ --no-pixel
```

For GitLab (Descope's [GitLab template](https://docs.descope.com/managing-environments/manage-envs-in-gitlab)),
run the same commands in the MR pipeline and attach `out/` as artifacts, or
commit them the same hash-folder way.

---

## Action reference

`uses: mrimboim/descope-flow-cicd-template/.github/actions/flow-diff@main`

| Input | Default | Notes |
|---|---|---|
| `flows-path` | `ProjectSnapshot/flows` | Snapshot flow dirs and/or single-file exports; mixed is fine |
| `output-path` | `flow-diffs` | Commit this directory to surface images in the PR |
| `base-ref` | *(empty)* | Empty = working tree vs `HEAD` (export-then-PR pipelines). In `pull_request` workflows pass the base SHA |
| `pixel-render` | `true` | Real screen renders via the Descope engine; `false` skips Chromium for fast CI |
| `image-url-prefix` | *(empty)* | Set to `https://github.com/OWNER/REPO/raw/BRANCH` when embedding the markdown in a PR body/comment |

| Output | Notes |
|---|---|
| `changed-count` | Flows that produced visual diffs |
| `markdown-file` | Path to a markdown fragment (one collapsible section per flow) ready for a PR body or sticky comment |

Notes: brand-new flows are listed in the markdown but not image-diffed (there is
nothing to compare against). `descope flow convert` is never needed — both
formats are read natively.

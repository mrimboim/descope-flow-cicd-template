# flow-diff

Git-style visual diff for Descope flow JSON exports. Used by
`.github/workflows/flows-open-pr.yml` to render diff images into promotion PRs.

## Usage

```bash
pip install cairosvg                # PNG output for graph panels
npm install                        # only needed for pixel-true screen rendering
npx playwright-core install --with-deps chromium-headless-shell

python3 flow_diff.py old.json new.json -o out/
```

Flags: `--no-pixel` (skip real-engine screen rendering — then no node/Chromium
needed), `--no-png` (SVG only, zero dependencies), `--no-noise-filter`.

## Output

| File | What |
|---|---|
| `00-overview` | Full flow graph at console coordinates, git-style colors |
| `10-cluster-*` | Zoom per changed region with 1-hop context |
| `20-screen-*` | Screen diff: craft tree + prop changes + embedded real render |
| `21-pixel-*` | OLD/NEW screens rendered with Descope's engine (`@descope/page-editor-components`), changed components outlined |
| `30-condition-*` | Per-condition panel: branches + atomics old→new (green banner) |
| `40-action-*` | Per-action panel: value-level field diffs + error handling (purple banner) |
| `50-connector-*` / `60-subflow-*` | Same for connectors (orange) / subflows (pink) |
| `summary.md` / `diff.json` | Changelog embedding the images / machine-readable diff |

## Diff semantics

Blocks: green `+` added, red dashed `−` removed, orange `Δ` modified (intrinsic
fields incl. screen contents). Lines: green added, red dashed removed, orange
solid rewired, **purple dotted = moved** (position-only changes show on the
connecting lines; the block gets a purple `↔`). `next`/`view` never count as
block modifications; derived fields are ignored; missing ≡ null ≡ "" so export
format drift is never a change; componentsVersion default-prop floods are
suppressed and reported once.

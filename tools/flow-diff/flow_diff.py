#!/usr/bin/env python3
"""
flow-diff — git-style visual diff for Descope flow JSON exports.

Usage:
    python3 flow_diff.py old.json new.json [-o OUTDIR] [--no-noise-filter] [--no-png]

Outputs (deterministic filenames, safe to commit):
    00-overview.svg/.png     full flow graph, changes highlighted
    10-cluster-<slug>.png    zoomed view per changed region
    20-screen-<slug>.png     structural screen diffs (old vs new)
    30-condition-<slug>.png  per-condition branch diffs
    40-action-<slug>.png     per-action field + error handling diffs
    50-connector-<slug>.png  per-connector diffs
    summary.md               changelog embedding the images
    diff.json                machine-readable diff
"""
import json, sys, os, re, argparse, html
from collections import defaultdict

# ---------------------------------------------------------------- constants
DERIVED_FIELDS = {"inputsMetadata", "allInputKeys", "inputKeys",
                  "calculatedInputKeys", "contextKeys"}
NOISE_PROP_NAMES = {"tooltipText"}          # known version-bump default props
NOISE_MIN_REPEAT = 3                        # same prop:value added to >=N nodes => noise
END_ACTIONS = {"logged-in"}

C = {  # colors
    "added":     "#1a7f37",
    "removed":   "#cf222e",
    "modified":  "#bf8700",
    "moved":     "#8250df",   # purple: moved = dotted lines + purple block; modified = orange block
    "unchanged": "#d0d7de",
    "text":      "#1f2328",
    "dim":       "#656d76",
    "bg":        "#ffffff",
    "card":      "#ffffff",
    "border":    "#d0d7de",
}
# console block palette: screens dark blue, actions purple, subflows pink,
# conditions green, connectors orange
TYPE_COLOR = {"screen": "#1f5c99", "condition": "#0e9f6e", "automated": "#8b5cf6",
              "connector": "#f59e0b", "flow": "#ec4899", "end": "#1f2328",
              "start": "#1f2328"}
TYPE_ICON = {"screen": "▢", "condition": "⑂", "automated": "⚡",
             "connector": "⬡", "flow": "⧉", "end": "◉", "start": "▶"}
CONNECTOR_ACTIONS = {"connector", "email-connector", "sms-connector",
                     "voice-connector", "im-connector"}

def esc(s): return html.escape(str(s), quote=True)
def tw(s, fs=12): return len(str(s)) * fs * 0.60   # crude text width estimate

# ---------------------------------------------------------------- load & normalize
def load_flow(path):
    with open(path) as f:
        return json.load(f)

def node_kind(task):
    action = task.get("action") or ""
    if action in END_ACTIONS: return "end"
    if (action in CONNECTOR_ACTIONS or "connector" in action
            or action.startswith("recaptcha")
            or task.get("connectorId") or task.get("connectorTemplate")):
        return "connector"
    return task.get("type") or "automated"

def normalize(flow):
    """Merge <id>.end grouped tasks, build node/edge model like the console does."""
    raw = dict(flow["contents"]["tasks"])
    tasks, remap = {}, {}
    for tid in raw:
        if tid.endswith(".end") and tid[:-4] in raw:
            remap[tid] = tid[:-4]
    for tid, t in raw.items():
        if tid in remap:
            continue
        tasks[tid] = dict(t)
    # merge grouped ends: absorb rules + errorHandlingV2 into base
    for endid, base in remap.items():
        et = raw[endid]
        b = tasks[base]
        rules = list((b.get("next") or {}).get("rules") or [])
        for r in (et.get("next") or {}).get("rules") or []:
            rules.append(dict(r))
        b["next"] = {"rules": rules}
        eh = dict(b.get("errorHandlingV2") or {})
        for k, v in (et.get("errorHandlingV2") or {}).items():
            eh.setdefault(k, v)
        if eh: b["errorHandlingV2"] = eh
    # edges: (src, interactionId, dst) with remapped/grouped ids, drop internal pair edges
    edges = []
    for tid, t in tasks.items():
        for r in (t.get("next") or {}).get("rules") or []:
            dst = remap.get(r.get("taskId"), r.get("taskId"))
            if dst == tid:
                continue  # internal send->verify edge of a grouped pair
            edges.append((tid, r.get("interactionId") or "", dst))
    screens = {s["screenId"]: s.get("contents") or {} for s in flow.get("screens") or []}
    meta = flow.get("metadata") or {}
    return {"tasks": tasks, "edges": edges, "screens": screens, "meta": meta,
            "flowId": flow.get("flowId", "flow"), "startTask": flow["contents"].get("startTask")}

# ---------------------------------------------------------------- diff engine
def deep_norm(v):
    """Serialization-noise normalizer: newer exports omit null values that older
    exports wrote explicitly (e.g. arguments.x.value: null, interactionId: "").
    Treat missing key == null == "" so format drift never reads as a change."""
    if isinstance(v, dict):
        return {k: deep_norm(x) for k, x in v.items() if x is not None and x != ""}
    if isinstance(v, list):
        return [deep_norm(x) for x in v]
    return v

def leaf_changes(a, b, prefix=""):
    """Recursive value-level diff: returns [[path, old, new], ...] of changed leaves."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in a: out.append([p, None, b[k]])
            elif k not in b: out.append([p, a[k], None])
            elif a[k] != b[k]: out.extend(leaf_changes(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        out.append([prefix, a, b])  # lists shown whole (order matters)
    elif a != b:
        out.append([prefix, a, b])
    return out

def strip_for_compare(t):
    # 'view' = position (tracked separately as "moved");
    # 'next' = connections (tracked separately as edge add/remove/rewire) —
    # neither counts as an intrinsic modification of the block itself.
    return deep_norm({k: v for k, v in t.items()
                      if k not in DERIVED_FIELDS and k not in ("view", "next")})

def diff_tasks(o, n):
    """'modified' and 'moved' are independent — a task can be both."""
    out = {"added": [], "removed": [], "modified": {}, "moved": [], "derived_only": []}
    ok, nk = set(o), set(n)
    out["added"] = sorted(nk - ok)
    out["removed"] = sorted(ok - nk)
    for tid in sorted(ok & nk):
        a, b = strip_for_compare(o[tid]), strip_for_compare(n[tid])
        if a != b:
            fields = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            out["modified"][tid] = fields
        if o[tid].get("view") != n[tid].get("view"):
            out["moved"].append(tid)
        if a == b and o[tid].get("view") == n[tid].get("view") and \
           {k: v for k, v in o[tid].items() if k not in ("view",)} != \
           {k: v for k, v in n[tid].items() if k not in ("view",)}:
            out["derived_only"].append(tid)
    return out

def diff_edges(oe, ne):
    os_, ns_ = set(oe), set(ne)
    added, removed = ns_ - os_, os_ - ns_
    rewired = []
    for (s, i, d) in sorted(added):
        for (s2, i2, d2) in sorted(removed):
            if s == s2 and i == i2 and d != d2:
                rewired.append({"src": s, "interactionId": i, "old": d2, "new": d})
                added.discard((s, i, d)); removed.discard((s2, i2, d2))
                break
    return {"added": sorted(added), "removed": sorted(removed), "rewired": rewired}

def diff_screens(o, n, noise_filter=True):
    """Craft-node level diff with version-bump noise suppression."""
    # pass 1: count identical prop additions across all common screens
    addition_counts = defaultdict(int)
    common = set(o) & set(n)
    for sid in common:
        for nid in set(o[sid]) & set(n[sid]):
            po = (o[sid][nid].get("props") or {})
            pn = (n[sid][nid].get("props") or {})
            for k in set(pn) - set(po):
                addition_counts[(k, json.dumps(pn[k], sort_keys=True))] += 1

    def is_noise(prop, oldv, newv):
        if not noise_filter: return False
        if prop in NOISE_PROP_NAMES: return True
        if oldv is _MISSING and addition_counts[(prop, json.dumps(newv, sort_keys=True))] >= NOISE_MIN_REPEAT:
            return True
        return False

    _MISSING = object()
    result = {"added": sorted(set(n) - set(o)), "removed": sorted(set(o) - set(n)),
              "modified": {}, "noise_suppressed": 0}
    for sid in sorted(common):
        co, cn = o[sid], n[sid]
        nodes_added = sorted(set(cn) - set(co))
        nodes_removed = sorted(set(co) - set(cn))
        prop_changes = {}  # nodeId -> [(prop, old, new)]
        for nid in sorted(set(co) & set(cn)):
            if co[nid] == cn[nid]:
                continue
            po, pn = co[nid].get("props") or {}, cn[nid].get("props") or {}
            changes = []
            for k in sorted(set(po) | set(pn)):
                a = po.get(k, _MISSING); b = pn.get(k, _MISSING)
                if a is _MISSING and b is _MISSING: continue
                if a == b: continue
                if is_noise(k, a, b):
                    result["noise_suppressed"] += 1
                    continue
                changes.append((k, None if a is _MISSING else a,
                                   None if b is _MISSING else b))
            # non-prop structural changes (parent / nodes order / type)
            for k in ("parent", "nodes", "type", "hidden", "displayName"):
                if co[nid].get(k) != cn[nid].get(k):
                    changes.append((f"<{k}>", co[nid].get(k), cn[nid].get(k)))
            if changes:
                prop_changes[nid] = changes
        if nodes_added or nodes_removed or prop_changes:
            result["modified"][sid] = {"nodes_added": nodes_added,
                                       "nodes_removed": nodes_removed,
                                       "prop_changes": prop_changes}
    return result

def atomic_str(a):
    t = (a.get("target") or {}).get("value", "?")
    op = a.get("operator", "?")
    p = (a.get("predicate") or {}).get("value", "")
    s = f"{t} {op}"
    if p not in ("", None): s += f" {p}"
    return s

def cond_map(task):
    return {c.get("interactionId"): c for c in task.get("conditions") or []}

def diff_conditions(o, n):
    out = {}
    for tid in set(o) & set(n):
        if o[tid].get("type") != "condition" and n[tid].get("type") != "condition":
            continue
        co, cn = cond_map(o[tid]), cond_map(n[tid])
        entries = []
        for iid in sorted(set(co) | set(cn)):
            a, b = co.get(iid), cn.get(iid)
            if deep_norm(a) == deep_norm(b): continue
            if a is None:
                entries.append({"branch": b.get("name", iid), "status": "added",
                                "new": [atomic_str(x) for x in b.get("atomicConditions") or []]})
            elif b is None:
                entries.append({"branch": a.get("name", iid), "status": "removed",
                                "old": [atomic_str(x) for x in a.get("atomicConditions") or []]})
            else:
                entries.append({"branch": b.get("name", iid), "status": "modified",
                                "old": [atomic_str(x) for x in a.get("atomicConditions") or []],
                                "new": [atomic_str(x) for x in b.get("atomicConditions") or []],
                                "renamed_from": a.get("name") if a.get("name") != b.get("name") else None})
        if entries:
            out[tid] = entries
    # condition tasks added/removed entirely are covered by task diff; include their branches
    return out

def diff_errors(o, n):
    rows = []
    for tid in sorted(set(o) | set(n)):
        eo = deep_norm((o.get(tid) or {}).get("errorHandlingV2") or {})
        en = deep_norm((n.get(tid) or {}).get("errorHandlingV2") or {})
        if eo == en: continue
        name = (n.get(tid) or o.get(tid) or {}).get("name", tid)
        for etype in sorted(set(eo) | set(en)):
            a, b = eo.get(etype), en.get(etype)
            if a == b: continue
            rows.append({"task": tid, "taskName": name, "error": etype,
                         "old": a, "new": b,
                         "status": "added" if a is None else "removed" if b is None else "modified"})
    return rows

def build_diff(old, new, noise_filter=True):
    td = diff_tasks(old["tasks"], new["tasks"])
    ed = diff_edges(old["edges"], new["edges"])
    sd = diff_screens(old["screens"], new["screens"], noise_filter)
    cd = diff_conditions(old["tasks"], new["tasks"])
    erd = diff_errors(old["tasks"], new["tasks"])
    # a screen task whose screen CONTENTS changed is a modified block
    for tid, t in new["tasks"].items():
        if tid in td["added"]:
            continue
        if t.get("screenId") in sd["modified"]:
            td["modified"].setdefault(tid, []).append("screen")
    # value-level diff per modified task ("what actually changed inside the field")
    td["field_changes"] = {}
    for tid in td["modified"]:
        if tid not in old["tasks"] or tid not in new["tasks"]:
            continue
        a = strip_for_compare(old["tasks"][tid]); b = strip_for_compare(new["tasks"][tid])
        # conditions & errorHandlingV2 get their own dedicated diff/panels
        for skip in ("conditions", "errorHandlingV2"):
            a.pop(skip, None); b.pop(skip, None)
        ch = leaf_changes(a, b)
        if ch:
            td["field_changes"][tid] = ch
    return {"flowId": new["flowId"],
            "componentsVersion": {"old": old["meta"].get("componentsVersion"),
                                  "new": new["meta"].get("componentsVersion")},
            "tasks": td, "edges": ed, "screens": sd, "conditions": cd, "errors": erd}

# ---------------------------------------------------------------- graph model for rendering
def interaction_label(flow, task, iid):
    if not iid: return ""
    if task.get("type") == "condition":
        for c in task.get("conditions") or []:
            if c.get("interactionId") == iid:
                return c.get("name", iid)
    sid = task.get("screenId")
    if sid and sid in flow["screens"]:
        node = flow["screens"][sid].get(iid)
        if node:
            p = node.get("props") or {}
            ch = p.get("children") or p.get("label")
            if isinstance(ch, str) and ch.strip():
                return ch.strip()
    return iid

def build_render_model(old, new, diff):
    """Nodes/edges union of both files, each tagged with a diff status."""
    tasks_o, tasks_n = old["tasks"], new["tasks"]
    all_ids = sorted(set(tasks_o) | set(tasks_n))
    td = diff["tasks"]
    node_status, node_moved = {}, set(td["moved"])
    for tid in all_ids:
        if tid in td["added"]: node_status[tid] = "added"
        elif tid in td["removed"]: node_status[tid] = "removed"
        elif tid in td["modified"]: node_status[tid] = "modified"
        else: node_status[tid] = "unchanged"

    # edges with status; rewired => two edges (old faded, new highlighted)
    edges = []
    added = set(map(tuple, diff["edges"]["added"]))
    removed = set(map(tuple, diff["edges"]["removed"]))
    rew_new = {(r["src"], r["interactionId"], r["new"]) for r in diff["edges"]["rewired"]}
    rew_old = {(r["src"], r["interactionId"], r["old"]) for r in diff["edges"]["rewired"]}
    for e in sorted(set(new["edges"]) | set(old["edges"])):
        if e in rew_new: st = "rewired-new"
        elif e in rew_old: st = "rewired-old"
        elif e in added: st = "added"
        elif e in removed: st = "removed"
        elif e[0] in node_moved or e[2] in node_moved:
            st = "moved"   # a moved block shows on its connecting lines, not the block
        else: st = "unchanged"
        edges.append({"src": e[0], "iid": e[1], "dst": e[2], "status": st})

    nodes = {}
    for tid in all_ids:
        t = tasks_n.get(tid) or tasks_o.get(tid)
        src_flow = new if tid in tasks_n else old
        view = t.get("view") or {}
        # interaction rows = ordered unique iids used by this node's edges
        iids, seen = [], set()
        for e in edges:
            if e["src"] == tid and e["iid"] not in seen:
                seen.add(e["iid"]); iids.append((e["iid"], e["status"]))
        def lbl(iid):
            # resolve from new first, then old (removed interactions only exist in old)
            for fl, tm in ((new, tasks_n), (old, tasks_o)):
                if tid in tm:
                    v = interaction_label(fl, tm[tid], iid)
                    if v != iid:
                        return v
            return iid
        rows = [{"iid": iid,
                 "label": lbl(iid),
                 "status": ("added" if st in ("added", "rewired-new") else
                            "removed" if st == "removed" else "unchanged")}
                for iid, st in iids]
        # dedupe rewired old/new rows (same iid appears once)
        kind = node_kind(t)
        nodes[tid] = {"id": tid, "name": t.get("name", tid), "kind": kind,
                      "x": view.get("x", 0), "y": view.get("y", 0),
                      "rows": rows, "status": node_status[tid],
                      "moved": tid in node_moved,
                      "modified_fields": td["modified"].get(tid, [])}
    return nodes, edges

# ---------------------------------------------------------------- SVG rendering
NODE_W, HEAD_H, ROW_H, PAD = 250, 34, 22, 10

def node_height(n):
    if n["kind"] in ("start", "end"): return 36
    return HEAD_H + max(1, len(n["rows"])) * ROW_H + PAD

def node_box(n):
    return (n["x"], n["y"], NODE_W, node_height(n))

def row_y(n, iid):
    for i, r in enumerate(n["rows"]):
        if r["iid"] == iid:
            return n["y"] + HEAD_H + i * ROW_H + ROW_H / 2
    return n["y"] + node_height(n) / 2

def clip(s, maxw, fs=12):
    s = str(s)
    maxc = max(3, int(maxw / (fs * 0.60)))
    return s if len(s) <= maxc else s[:maxc - 1] + "…"

def svg_node(n):
    x, y, w, h = node_box(n)
    st, kind = n["status"], n["kind"]
    moved_only = n.get("moved") and st == "unchanged"
    if moved_only:
        st = "moved"  # purple block; if also modified, orange (modified) wins
    tc = TYPE_COLOR.get(kind, "#2563eb")
    parts = []
    op = 0.35 if st == "unchanged" else 1.0
    parts.append(f'<g opacity="{op}">')
    if kind in ("start", "end"):
        label = "Start" if kind == "start" else n["name"] if n["name"] != "Generate JWT" else "End"
        stroke = C.get(st, C["border"]) if st != "unchanged" else C["border"]
        dash = ' stroke-dasharray="6 4"' if st == "removed" else ""
        parts.append(f'<rect x="{x}" y="{y}" rx="18" width="{w}" height="{h}" fill="#f6f8fa" '
                     f'stroke="{stroke}" stroke-width="{2 if st != "unchanged" else 1.5}"{dash}/>')
        parts.append(f'<text x="{x + w/2}" y="{y + h/2 + 4}" font-size="13" font-weight="600" '
                     f'text-anchor="middle" fill="{C["text"]}">{TYPE_ICON[kind]} {esc(clip(label, w-40, 13))}</text>')
    else:
        stroke = C.get(st, C["border"]) if st != "unchanged" else C["border"]
        sw = 2.5 if st != "unchanged" else 1
        dash = ' stroke-dasharray="7 5"' if st == "removed" else ""
        parts.append(f'<rect x="{x}" y="{y}" rx="10" width="{w}" height="{h}" fill="{C["card"]}" '
                     f'stroke="{stroke}" stroke-width="{sw}"{dash}/>')
        parts.append(f'<path d="M{x} {y+10} q0 -10 10 -10 h{w-20} q10 0 10 10 v{HEAD_H-10} h-{w} z" fill="{tc}" fill-opacity="0.22"/>')
        parts.append(f'<text x="{x+10}" y="{y+22}" font-size="13" font-weight="700" fill="{tc}">'
                     f'{TYPE_ICON.get(kind,"")} {esc(clip(n["name"], w-60, 13))}</text>')
        for i, r in enumerate(n["rows"]):
            ry = y + HEAD_H + i * ROW_H
            rc = C.get(r["status"], C["dim"]) if r["status"] != "unchanged" else C["dim"]
            weight = "600" if r["status"] != "unchanged" else "400"
            parts.append(f'<text x="{x+12}" y="{ry+15}" font-size="11" fill="{rc}" '
                         f'font-weight="{weight}">{esc(clip(r["label"], w-40, 11))}</text>')
            parts.append(f'<circle cx="{x+w}" cy="{ry+ROW_H/2}" r="3.5" fill="{rc}"/>')
    # status badge (moved+modified: block is orange Δ, its lines stay purple dotted)
    if st in ("added", "removed", "modified", "moved"):
        badge = {"added": "+", "removed": "−", "modified": "Δ", "moved": "↔"}[st]
        parts.append(f'<circle cx="{x+w}" cy="{y}" r="11" fill="{C[st]}"/>')
        parts.append(f'<text x="{x+w}" y="{y+4.5}" font-size="13" font-weight="700" '
                     f'text-anchor="middle" fill="#fff">{badge}</text>')
    parts.append("</g>")
    return "".join(parts)

def svg_edge(e, nodes):
    src, dst = nodes.get(e["src"]), nodes.get(e["dst"])
    if not src or not dst: return ""
    x1 = src["x"] + NODE_W
    y1 = row_y(src, e["iid"])
    if src["kind"] in ("start", "end"):
        x1 = src["x"] + NODE_W; y1 = src["y"] + node_height(src) / 2
    x2 = dst["x"]; y2 = dst["y"] + node_height(dst) / 2
    st = e["status"]
    color = {"added": C["added"], "removed": C["removed"], "rewired-new": C["modified"],
             "rewired-old": C["removed"], "moved": C["moved"], "unchanged": "#b1b8c0"}[st]
    width = 1.2 if st == "unchanged" else (1.8 if st == "moved" else 2.2)
    op = 0.5 if st == "unchanged" else (0.45 if st == "rewired-old" else 1.0)
    dash = (' stroke-dasharray="7 5"' if st in ("removed", "rewired-old")
            else ' stroke-dasharray="2 4"' if st == "moved" else "")
    dx = max(50, abs(x2 - x1) * 0.45)
    path = f"M{x1} {y1} C {x1+dx} {y1}, {x2-dx} {y2}, {x2-6} {y2}"
    marker = {"added": "arr-added", "removed": "arr-removed", "rewired-new": "arr-modified",
              "rewired-old": "arr-removed", "moved": "arr-moved", "unchanged": "arr-dim"}[st]
    return (f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'opacity="{op}"{dash} marker-end="url(#{marker})"/>')

MARKERS = "".join(
    f'<marker id="arr-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
    f'markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L10 5 L0 10 z" fill="{c}"/></marker>'
    for k, c in [("added", C["added"]), ("removed", C["removed"]),
                 ("modified", C["modified"]), ("moved", C["moved"]), ("dim", "#b1b8c0")])

def legend_svg(x, y):
    # solid swatch with the same badge symbol used on the blocks; moved also
    # shows the dotted-line treatment its connections get
    items = [("added", "Added", "+", False), ("removed", "Removed", "−", False),
             ("modified", "Modified", "Δ", False), ("moved", "Moved", "↔", True),
             ("unchanged", "Unchanged", "", False)]
    parts, cx = [], x
    for key, lbl, sym, dotted_line in items:
        parts.append(f'<rect x="{cx}" y="{y}" width="16" height="16" rx="4" fill="{C[key]}"/>')
        if sym:
            parts.append(f'<text x="{cx+8}" y="{y+12.5}" font-size="12" font-weight="700" '
                         f'text-anchor="middle" fill="#fff">{sym}</text>')
        cx += 21
        if dotted_line:
            parts.append(f'<line x1="{cx}" y1="{y+8}" x2="{cx+18}" y2="{y+8}" stroke="{C[key]}" '
                         f'stroke-width="2.5" stroke-dasharray="2 4"/>')
            cx += 22
        parts.append(f'<text x="{cx}" y="{y+12.5}" font-size="12" fill="{C["text"]}">{lbl}</text>')
        cx += tw(lbl, 12) + 26
    return "".join(parts)

def render_graph(nodes, edges, title, subtitle="", only_ids=None):
    ns = {k: v for k, v in nodes.items() if not only_ids or k in only_ids}
    es = [e for e in edges if (not only_ids) or (e["src"] in only_ids and e["dst"] in only_ids)]
    if not ns: return None
    xs = [v["x"] for v in ns.values()]; ys = [v["y"] for v in ns.values()]
    minx, miny = min(xs) - 60, min(ys) - 100
    maxx = max(v["x"] + NODE_W for v in ns.values()) + 60
    maxy = max(v["y"] + node_height(v) for v in ns.values()) + 40
    w, h = maxx - minx, maxy - miny
    body = []
    body.append(f'<rect x="{minx}" y="{miny}" width="{w}" height="{h}" fill="{C["bg"]}"/>')
    body.append(f'<text x="{minx+24}" y="{miny+34}" font-size="20" font-weight="700" '
                f'fill="{C["text"]}">{esc(title)}</text>')
    if subtitle:
        body.append(f'<text x="{minx+24}" y="{miny+54}" font-size="12" fill="{C["dim"]}">{esc(subtitle)}</text>')
    body.append(legend_svg(minx + 24, miny + 64))
    # unchanged edges under, changed edges over nodes' edges layer
    for e in sorted(es, key=lambda e: e["status"] != "unchanged"):
        body.append(svg_edge(e, ns))
    for n in sorted(ns.values(), key=lambda n: n["status"] != "unchanged"):
        body.append(svg_node(n))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {miny} {w} {h}" '
            f'width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">'
            f'<defs>{MARKERS}</defs>{"".join(body)}</svg>')

# ---------------------------------------------------------------- clusters
def change_clusters(nodes, edges, diff):
    changed = {tid for tid, n in nodes.items() if n["status"] in ("added", "removed", "modified")}
    for e in edges:
        if e["status"] not in ("unchanged", "moved"):  # pure moves don't make a "changed region"
            changed.add(e["src"]); changed.add(e["dst"])
    if not changed: return []
    adj = defaultdict(set)
    for e in edges:
        adj[e["src"]].add(e["dst"]); adj[e["dst"]].add(e["src"])
    seen, clusters = set(), []
    for start in sorted(changed):
        if start in seen: continue
        comp, stack = set(), [start]
        while stack:
            cur = stack.pop()
            if cur in comp: continue
            comp.add(cur)
            for nb in adj[cur]:
                if nb in changed and nb not in comp:
                    stack.append(nb)
        seen |= comp
        ctx = set(comp)
        for e in edges:  # 1-hop context
            if e["src"] in comp: ctx.add(e["dst"])
            if e["dst"] in comp: ctx.add(e["src"])
        clusters.append({"changed": sorted(comp), "context": sorted(ctx)})
    return clusters

def slugify(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:48] or "change"

def cluster_name(cluster, nodes):
    for tid in cluster["changed"]:
        if nodes[tid]["status"] == "added":
            return nodes[tid]["name"]
    return nodes[cluster["changed"][0]]["name"]

# ---------------------------------------------------------------- screen panels
def craft_tree_order(contents, root="ROOT"):
    """DFS the craft tree -> [(nodeId, depth)]"""
    out = []
    def walk(nid, depth):
        node = contents.get(nid)
        if not node: return
        out.append((nid, depth))
        for ch in node.get("nodes") or []:
            walk(ch, depth + 1)
        for ch in (node.get("linkedNodes") or {}).values():
            walk(ch, depth + 1)
    walk(root, 0)
    known = {nid for nid, _ in out}
    for nid in contents:  # orphans
        if nid not in known:
            out.append((nid, 0))
    return out

def craft_label(node):
    t = (node.get("type") or {}).get("resolvedName") or node.get("displayName") or "?"
    p = node.get("props") or {}
    txt = p.get("children") if isinstance(p.get("children"), str) else p.get("label") or p.get("placeholder") or ""
    return t, (txt or "")

def png_size(path):
    import struct
    with open(path, "rb") as f:
        head = f.read(24)
    w, h = struct.unpack(">II", head[16:24])
    return w, h

def render_screen_panel(title, old_c, new_c, changes, subtitle="", pixel_png=None):
    """Two columns (old/new) of the craft tree with diff highlighting + prop change list."""
    colw, rowh, indent = 380, 26, 16
    changed_nodes = set(changes.get("prop_changes") or {})
    added_nodes = set(changes.get("nodes_added") or [])
    removed_nodes = set(changes.get("nodes_removed") or [])

    def col(contents, x0, y0, side):
        parts, y = [], y0
        for nid, depth in craft_tree_order(contents):
            t, txt = craft_label(contents[nid])
            if side == "old":
                st = "removed" if nid in removed_nodes else "modified" if nid in changed_nodes else None
            else:
                st = "added" if nid in added_nodes else "modified" if nid in changed_nodes else None
            fill = {"added": "#e6f4ea", "removed": "#fdecea", "modified": "#fff8e1"}.get(st, "#f6f8fa")
            stroke = C.get(st, C["border"]) if st else C["border"]
            x = x0 + depth * indent
            w = colw - depth * indent
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{rowh-5}" rx="5" '
                         f'fill="{fill}" stroke="{stroke}" stroke-width="{1.6 if st else 0.8}"/>')
            label = t + (f'  “{clip(txt, 200, 11)}”' if txt else "")
            parts.append(f'<text x="{x+8}" y="{y+14.5}" font-size="11" fill="{C["text"]}">{esc(clip(label, w-16, 11))}</text>')
            y += rowh
        return parts, y

    rows_old = len(craft_tree_order(old_c)) if old_c else 0
    rows_new = len(craft_tree_order(new_c)) if new_c else 0
    prop_lines = []
    for nid, chs in (changes.get("prop_changes") or {}).items():
        t, txt = craft_label((new_c or old_c).get(nid, {}))
        for (prop, a, b) in chs:
            if a is None:
                prop_lines.append((f'{t} {("“"+clip(txt,120,11)+"”") if txt else nid}', f'+ {prop} = {json.dumps(b)}', "added"))
            elif b is None:
                prop_lines.append((f'{t} {("“"+clip(txt,120,11)+"”") if txt else nid}', f'− {prop} (was {json.dumps(a)})', "removed"))
            else:
                prop_lines.append((f'{t} {("“"+clip(txt,120,11)+"”") if txt else nid}', f'{prop}: {json.dumps(a)} → {json.dumps(b)}', "modified"))
    header_h = 78
    body_h = max(rows_old, rows_new) * rowh + 30
    props_h = (len(prop_lines) + 1) * 20 + 20 if prop_lines else 0
    W = 2 * colw + 3 * 24
    # embedded pixel-true render (Descope engine), scaled to panel width
    pix_w = pix_h = 0
    pix_b64 = None
    if pixel_png and os.path.exists(pixel_png):
        import base64
        pw, ph = png_size(pixel_png)
        pix_w = W - 48
        pix_h = int(ph * pix_w / pw)
        with open(pixel_png, "rb") as f:
            pix_b64 = base64.b64encode(f.read()).decode()
    H = header_h + body_h + props_h + (pix_h + 40 if pix_b64 else 0) + 24
    p = [f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>']
    p.append(f'<text x="24" y="34" font-size="18" font-weight="700" fill="{C["text"]}">{esc(title)}</text>')
    if subtitle:
        p.append(f'<text x="24" y="54" font-size="11" fill="{C["dim"]}">{esc(subtitle)}</text>')
    p.append(f'<text x="24" y="{header_h-6}" font-size="12" font-weight="700" fill="{C["dim"]}">OLD</text>')
    p.append(f'<text x="{24+colw+24}" y="{header_h-6}" font-size="12" font-weight="700" fill="{C["dim"]}">NEW</text>')
    if old_c:
        parts, _ = col(old_c, 24, header_h, "old"); p += parts
    else:
        p.append(f'<text x="24" y="{header_h+20}" font-size="12" fill="{C["dim"]}">(screen did not exist)</text>')
    if new_c:
        parts, _ = col(new_c, 24 + colw + 24, header_h, "new"); p += parts
    else:
        p.append(f'<text x="{24+colw+24}" y="{header_h+20}" font-size="12" fill="{C["dim"]}">(screen deleted)</text>')
    y = header_h + body_h
    if prop_lines:
        p.append(f'<text x="24" y="{y}" font-size="12" font-weight="700" fill="{C["text"]}">Property changes</text>')
        y += 8
        for (where, what, st) in prop_lines:
            y += 20
            p.append(f'<text x="32" y="{y}" font-size="11" fill="{C[st]}">{esc(clip(where, 300, 11))}   '
                     f'<tspan fill="{C["text"]}">{esc(clip(what, 460, 11))}</tspan></text>')
        y += 20
    if pix_b64:
        p.append(f'<text x="24" y="{y+14}" font-size="12" font-weight="700" fill="{C["text"]}">'
                 f'Rendered screen (Descope engine)</text>')
        p.append(f'<image x="24" y="{y+24}" width="{pix_w}" height="{pix_h}" '
                 f'href="data:image/png;base64,{pix_b64}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'font-family="Helvetica, Arial, sans-serif">{"".join(p)}</svg>')

# ---------------------------------------------------------------- tables (blocks)
def render_table(title, headers, rows, col_ws, row_status, accent=None, subtitle=""):
    rowh, x0, y0 = 26, 24, 88 if accent else 70
    W = sum(col_ws) + 2 * x0
    H = y0 + (len(rows) + 1) * rowh + 24
    p = [f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>']
    if accent:  # colored banner matching the block type, like the canvas node header
        p.append(f'<rect x="0" y="0" width="{W}" height="52" fill="{accent}" fill-opacity="0.22"/>')
        p.append(f'<rect x="0" y="0" width="6" height="52" fill="{accent}"/>')
        p.append(f'<text x="24" y="33" font-size="18" font-weight="700" fill="{accent}">{esc(title)}</text>')
        if subtitle:
            p.append(f'<text x="24" y="{y0-18}" font-size="11" fill="{C["dim"]}">{esc(subtitle)}</text>')
    else:
        p.append(f'<text x="24" y="36" font-size="18" font-weight="700" fill="{C["text"]}">{esc(title)}</text>')
    x = x0
    for hname, wcol in zip(headers, col_ws):
        p.append(f'<text x="{x}" y="{y0}" font-size="11" font-weight="700" fill="{C["dim"]}">{esc(hname.upper())}</text>')
        x += wcol
    y = y0 + 10
    for i, row in enumerate(rows):
        st = row_status[i]
        if st:
            p.append(f'<rect x="{x0-8}" y="{y}" width="{W-2*x0+16}" height="{rowh-4}" rx="4" '
                     f'fill="{ {"added":"#e6f4ea","removed":"#fdecea","modified":"#fff8e1"}.get(st, "#fff") }"/>')
        x = x0
        for val, wcol in zip(row, col_ws):
            p.append(f'<text x="{x}" y="{y+16}" font-size="11" fill="{C["text"]}">{esc(clip(val, wcol-14, 11))}</text>')
            x += wcol
        y += rowh
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'font-family="Helvetica, Arial, sans-serif">{"".join(p)}</svg>')

def eh_str(e):
    if e is None: return "—"
    s = e.get("errorHandlingType", "?")
    if e.get("errorMessage"): s += f' msg="{e["errorMessage"]}"'
    return s

# ---------------------------------------------------------------- summary.md
def make_summary(diff, nodes, files, old, new):
    L = []
    cv = diff["componentsVersion"]
    L.append(f'# Flow diff: `{diff["flowId"]}`\n')
    if cv["old"] != cv["new"]:
        L.append(f'> Components version bump: **{cv["old"]} → {cv["new"]}** '
                 f'({diff["screens"]["noise_suppressed"]} default-prop changes suppressed as upgrade noise)\n')
    td, ed = diff["tasks"], diff["edges"]
    L.append("## Changes\n")
    for tid in td["added"]:
        n = nodes[tid]
        L.append(f'- 🟢 **Added {n["kind"]}** `{tid}` — {n["name"]}')
    for tid in td["removed"]:
        n = nodes[tid]
        L.append(f'- 🔴 **Removed {n["kind"]}** `{tid}` — {n["name"]}')
    for tid, fields in td["modified"].items():
        L.append(f'- 🟡 **Modified** `{tid}` — {nodes[tid]["name"]} ({", ".join(fields)})')
    for r in ed["rewired"]:
        L.append(f'- 🟡 **Rewired** {nodes[r["src"]]["name"]} ·{r["interactionId"]}· : '
                 f'{nodes[r["old"]]["name"]} → **{nodes[r["new"]]["name"]}**')
    for (s, i, d) in ed["added"]:
        L.append(f'- 🟢 **New connection** {nodes[s]["name"]} ·{i}· → {nodes[d]["name"]}')
    for (s, i, d) in ed["removed"]:
        L.append(f'- 🔴 **Removed connection** {nodes[s]["name"]} ·{i}· → {nodes[d]["name"]}')
    if td["moved"]:
        L.append(f'- 🟣 Moved (position only, shown on connecting lines): '
                 f'{", ".join(nodes[t]["name"] for t in td["moved"])}')
    for tid, entries in diff["conditions"].items():
        for e in entries:
            L.append(f'- 🟡 **Condition** {nodes[tid]["name"]} / branch "{e["branch"]}" {e["status"]}')
    for r in diff["errors"]:
        L.append(f'- 🟡 **Error handling** {r["taskName"]} · {r["error"]}: {eh_str(r["old"])} → {eh_str(r["new"])}')
    L.append("\n## Overview\n")
    L.append(f'![overview]({files["overview"]})\n')
    if files.get("clusters"):
        L.append("## Changed regions\n")
        for f in files["clusters"]:
            L.append(f'![cluster]({f})\n')
    if files.get("screens"):
        L.append("## Screen changes\n")
        for f in files["screens"]:
            L.append(f'![screen]({f})\n')
    for cat, heading in [("condition", "Condition changes"), ("action", "Action changes"),
                         ("connector", "Connector changes"), ("subflow", "Subflow changes")]:
        imgs = [f for c, f in files.get("blocks", []) if c == cat]
        if imgs:
            L.append(f"## {heading}\n")
            for f in imgs:
                L.append(f'![{cat}]({f})\n')
    return "\n".join(L) + "\n"

# ---------------------------------------------------------------- main
def write_svg_png(svg, outdir, name, png=True):
    svgp = os.path.join(outdir, name + ".svg")
    with open(svgp, "w") as f:
        f.write(svg)
    if png:
        try:
            import cairosvg
            cairosvg.svg2png(url=svgp, write_to=os.path.join(outdir, name + ".png"), scale=2)
            return name + ".png"
        except Exception as ex:
            print(f"  (png skipped for {name}: {ex})", file=sys.stderr)
    return name + ".svg"

def main():
    ap = argparse.ArgumentParser(description="Visual git-style diff for Descope flow JSON exports")
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("-o", "--out", default="flow-diff")
    ap.add_argument("--no-noise-filter", action="store_true")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--no-pixel", action="store_true",
                    help="skip pixel-true screen rendering (needs node + render_screens.js)")
    ap.add_argument("--renderer", default=None,
                    help="path to render_screens.js (default: next to this script)")
    args = ap.parse_args()

    fo, fn = load_flow(args.old), load_flow(args.new)
    old, new = normalize(fo), normalize(fn)

    # swapped-order heuristic
    def vt(v): return tuple(int(x) for x in re.findall(r"\d+", v or "0"))
    if vt(old["meta"].get("componentsVersion")) > vt(new["meta"].get("componentsVersion")):
        print("⚠ warning: 'old' has a NEWER componentsVersion than 'new' — args may be swapped", file=sys.stderr)

    diff = build_diff(old, new, noise_filter=not args.no_noise_filter)
    nodes, edges = build_render_model(old, new, diff)
    os.makedirs(args.out, exist_ok=True)
    # best-effort cleanup of previous outputs so renamed/obsolete panels don't linger
    for f in os.listdir(args.out):
        if re.match(r"^\d\d-.*\.(png|svg)$", f) or f in ("summary.md", "diff.json"):
            try: os.remove(os.path.join(args.out, f))
            except OSError: pass
    png = not args.no_png
    files = {}

    # overview
    cv = diff["componentsVersion"]
    sub = f'{args.old.split("/")[-1]} → {args.new.split("/")[-1]}   components {cv["old"]} → {cv["new"]}'
    svg = render_graph(nodes, edges, f'Flow diff: {diff["flowId"]}', sub)
    files["overview"] = write_svg_png(svg, args.out, "00-overview", png)

    # clusters
    files["clusters"] = []
    for i, cl in enumerate(change_clusters(nodes, edges, diff)):
        name = cluster_name(cl, nodes)
        svg = render_graph(nodes, edges, f'Changed region: {name}',
                           f'{len(cl["changed"])} changed step(s), shown with 1-hop context',
                           only_ids=set(cl["context"]))
        if svg:
            fn_ = write_svg_png(svg, args.out, f'10-cluster-{i}-{slugify(name)}', png)
            files["clusters"].append(fn_)

    # pixel-true screen rendering via Descope's engine (@descope/page-editor-components)
    # runs FIRST so the renders can be embedded inside the 20-screen-* panels
    pixel_files = {}  # sid -> png path
    changed_sids = list(diff["screens"]["modified"]) + diff["screens"]["added"] + \
                   diff["screens"]["removed"]
    if not args.no_pixel and changed_sids:
        import subprocess, shutil
        renderer = args.renderer or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "render_screens.js")
        if shutil.which("node") and os.path.exists(renderer):
            try:
                # per-screen change map so the renderer outlines changed components
                hl = {}
                for sid in changed_sids:
                    ch = diff["screens"]["modified"].get(sid, {})
                    hl[sid] = {"added": ch.get("nodes_added", []),
                               "removed": ch.get("nodes_removed", []),
                               "changed": list(ch.get("prop_changes", {}))}
                changes_path = os.path.join(args.out, ".pixel-changes.json")
                with open(changes_path, "w") as f:
                    json.dump(hl, f)
                r = subprocess.run(["node", renderer, args.old, args.new,
                                    os.path.abspath(args.out), os.path.abspath(changes_path)],
                                   cwd=os.path.dirname(renderer), capture_output=True,
                                   text=True, timeout=300)
                if r.returncode == 0:
                    for ln in r.stdout.splitlines():
                        if ln.startswith("21-pixel-"):
                            fn_ = ln.split()[0]
                            sid = fn_[len("21-pixel-"):-len(".png")]
                            pixel_files[sid] = os.path.join(args.out, fn_)
                else:
                    print(f"  (pixel rendering skipped: {r.stderr.strip().splitlines()[-1][:120] if r.stderr else 'error'})",
                          file=sys.stderr)
            except Exception as ex:
                print(f"  (pixel rendering skipped: {ex})", file=sys.stderr)

    # screens — map screenId -> task names for titles
    sid2names = defaultdict(list)
    for tid, t in {**old["tasks"], **new["tasks"]}.items():
        if t.get("screenId"):
            sid2names[t["screenId"]].append(t.get("name", tid))
    files["screens"] = []
    for sid, ch in diff["screens"]["modified"].items():
        title = " / ".join(sorted(set(sid2names.get(sid) or [sid])))
        svg = render_screen_panel(f'Screen changed: {title}', old["screens"].get(sid),
                                  new["screens"].get(sid), ch, subtitle=sid,
                                  pixel_png=pixel_files.get(sid))
        files["screens"].append(write_svg_png(svg, args.out, f'20-screen-{slugify(title)}', png))
    for sid in diff["screens"]["added"]:
        title = " / ".join(sorted(set(sid2names.get(sid) or [sid])))
        svg = render_screen_panel(f'Screen added: {title}', None, new["screens"].get(sid),
                                  {}, subtitle=sid, pixel_png=pixel_files.get(sid))
        files["screens"].append(write_svg_png(svg, args.out, f'20-screen-added-{slugify(title)}', png))
    for sid in diff["screens"]["removed"]:
        title = " / ".join(sorted(set(sid2names.get(sid) or [sid])))
        svg = render_screen_panel(f'Screen removed: {title}', old["screens"].get(sid), None,
                                  {}, subtitle=sid, pixel_png=pixel_files.get(sid))
        files["screens"].append(write_svg_png(svg, args.out, f'20-screen-removed-{slugify(title)}', png))

    # per-block change panels (conditions / actions / connectors / subflows),
    # each with its own colored banner; error-handling changes fold into the
    # owning block's panel instead of a global errors image
    err_by_task = defaultdict(list)
    for r in diff["errors"]:
        err_by_task[r["task"]].append(r)
    field_changes = diff["tasks"].get("field_changes", {})
    block_tids = set(diff["conditions"]) | set(err_by_task) | set(field_changes)
    files["blocks"] = []  # (category, filename)
    CAT = {"condition": ("condition", "30-condition"), "automated": ("action", "40-action"),
           "connector": ("connector", "50-connector"), "flow": ("subflow", "60-subflow"),
           "end": ("action", "40-action")}
    for tid in sorted(block_tids):
        node = nodes.get(tid)
        if not node or node["status"] in ("added", "removed"):
            continue  # brand-new/deleted blocks are covered by the graph views
        kind = node["kind"]
        if kind == "screen":
            # screen-content changes live in the 20-screen panels; only surface
            # error-handling rows here (rare on screens)
            if tid not in err_by_task:
                continue
            field_changes = {**field_changes, tid: []}
        rows, sts = [], []
        for e in diff["conditions"].get(tid, []):
            rows.append([f'branch "{e["branch"]}"' +
                         (f' (was "{e["renamed_from"]}")' if e.get("renamed_from") else ""),
                         "; ".join(e.get("old") or []) or "—",
                         "; ".join(e.get("new") or []) or "—"])
            sts.append(e["status"])
        for path, a, b in field_changes.get(tid, []):
            rows.append([path, "—" if a is None else json.dumps(a),
                         "—" if b is None else json.dumps(b)])
            sts.append("modified")
        for r in err_by_task.get(tid, []):
            rows.append([f'error · {r["error"]}', eh_str(r["old"]), eh_str(r["new"])])
            sts.append(r["status"])
        if not rows:
            continue
        cat, prefix = CAT.get(kind, ("action", "40-action"))
        svg = render_table(f'{cat.capitalize()} changed: {node["name"]}',
                           ["what", "old", "new"], rows, [280, 320, 320], sts,
                           accent=TYPE_COLOR.get(kind, "#8b5cf6"), subtitle=f"task {tid}")
        fn_ = write_svg_png(svg, args.out, f'{prefix}-{slugify(node["name"])}', png)
        files["blocks"].append((cat, fn_))

    with open(os.path.join(args.out, "diff.json"), "w") as f:
        json.dump(diff, f, indent=1, sort_keys=True)
    with open(os.path.join(args.out, "summary.md"), "w") as f:
        f.write(make_summary(diff, nodes, files, old, new))

    n_changes = (len(diff["tasks"]["added"]) + len(diff["tasks"]["removed"]) +
                 len(diff["tasks"]["modified"]) + len(diff["edges"]["added"]) +
                 len(diff["edges"]["removed"]) + len(diff["edges"]["rewired"]))
    print(f'✓ {n_changes} flow changes, {len(files["screens"])} screen panel(s), '
          f'{len(diff["errors"])} error-handling change(s) → {args.out}/')

if __name__ == "__main__":
    main()

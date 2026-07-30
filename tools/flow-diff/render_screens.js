#!/usr/bin/env node
/**
 * render_screens.js — screen renderer for Descope flow-diff.
 *
 * Uses Descope's actual rendering engine (@descope/page-editor-components — the
 * same craft-JSON -> HTML mapper the screen-renderer-service uses), styled like
 * the flow builder's screen editor. Changed components are outlined directly on
 * the OLD/NEW renders using the semantic diff (green added / red removed /
 * orange modified) instead of a raw pixel diff.
 *
 * Usage: node render_screens.js old.json new.json outdir [changes.json]
 *   changes.json: { "<screenId>": { "added": [ids], "removed": [ids], "changed": [ids] } }
 *   (if omitted, renders every screen with no highlights)
 * Emits: <outdir>/21-pixel-<screenId>.png   (OLD | NEW side by side)
 */
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const comps = require('@descope/page-editor-components');
const { chromium } = require('playwright-core');
const { PNG } = require('pngjs');

const PKG_DIST = path.dirname(require.resolve('@descope/page-editor-components'));
const STYLE = fs.readFileSync(path.join(PKG_DIST, 'style.css'), 'utf8');
const CUSTOM = fs.readFileSync(path.join(PKG_DIST, 'custom.css'), 'utf8');
const WIDTH = 480;
const CANVAS_PAD = 28;
const COLW = WIDTH + CANVAS_PAD * 2;

const HL = { added: '#2da44e', removed: '#cf222e', changed: '#d4a72c' };

// map craft resolvedNames -> page-editor-components exports
const ALIASES = {
  CodeInput: 'Code', PhoneInput: 'Phone', RecaptchaV2: 'Recaptcha',
  EmailInput: 'Input', FullNameInput: 'Input', CustomIdentifierInput: 'Input',
  GoogleButton: 'Button', AppleButton: 'Button', PasskeyButton: 'Button',
  BiometricsButton: 'Button', PollingLoader: 'Loader',
};

function buildElement(contents, nid) {
  const n = contents[nid];
  if (!n) return null;
  let name = (n.type && n.type.resolvedName) || n.displayName || 'Container';
  if (name === 'ErrorMessage') {
    // match the flow builder's screen editor preview
    return React.createElement('div', { key: nid, id: (n.props || {}).id || nid,
      style: { color: '#e02424', fontSize: '14px', width: '100%', textAlign: 'center' } },
      'Sample Error Message');
  }
  name = ALIASES[name] || name;
  const C = comps[name] || comps[name.replace(/(Input|Button)$/, '')] ||
    (/Button$/.test(name) ? comps.Button : /Input$/.test(name) ? comps.Input : comps.Container);
  const kids = (n.nodes || []).map((c) => buildElement(contents, c)).filter(Boolean);
  const props = { key: nid };
  for (const [k, v] of Object.entries(n.props || {})) {
    props[k] = typeof v === 'boolean' ? String(v) : v; // web-component style attrs
  }
  return React.createElement(C, props, ...(kids.length ? kids : []));
}

function highlightCss(hl, side) {
  if (!hl) return '';
  const rules = [];
  const outline = (ids, color) => {
    for (const id of ids || []) {
      rules.push(`#frame [id="${id}"], #frame [name="${id}"] {
        outline: 3px solid ${color} !important; outline-offset: 3px; }`);
    }
  };
  outline(hl.changed, HL.changed);                       // modified: both sides
  if (side === 'old') outline(hl.removed, HL.removed);   // removed: old side
  if (side === 'new') outline(hl.added, HL.added);       // added: new side
  return rules.join('\n');
}

function screenHtml(contents, hl, side) {
  let body = '';
  try { body = renderToStaticMarkup(buildElement(contents, 'ROOT')); }
  catch (e) { body = `<pre>render failed: ${e.message}</pre>`; }
  body = body.replace(/100%%/g, '100%'); // craft stores doubled %% in width props
  return `<!doctype html><html><head><meta charset="utf-8">
  <style>${STYLE}</style><style>${CUSTOM}</style>
  <style>
    html,body { margin:0; background:#333c49;
      font-family: Roboto, "Helvetica Neue", Helvetica, Arial, sans-serif; }
    body > * { box-sizing: border-box; }
    #canvas { background:#333c49; padding:${CANVAS_PAD}px; width:${COLW}px; } /* builder canvas */
    #frame { width:${WIDTH}px; min-height:200px; margin:0 auto;
      border:0; background:#fff; overflow:hidden; border-radius:24px;
      outline:1px dotted #cbd2da; outline-offset:4px; }
    #frame .descope-container { max-width:100%; }
    #frame span, #frame a { font-style: normal; }
    ${highlightCss(hl, side)}
  </style></head><body><div id="canvas"><div id="frame">${body}</div></div></body></html>`;
}

async function shoot(page, html) {
  await page.setContent(html, { waitUntil: 'networkidle' });
  const el = await page.$('#canvas');
  return PNG.sync.read(await el.screenshot());
}

function composite(oldPng, newPng, title, hasOld, hasNew) {
  const GAP = 24, HEAD = 64, LBL = 26, SCALE = 2; // screenshots are 2x retina
  const dw = (p) => p.width / SCALE, dh = (p) => p.height / SCALE;
  const b64 = (p) => PNG.sync.write(p).toString('base64');
  const cols = [];
  if (hasOld) cols.push(['OLD', oldPng, '#cf222e']);
  if (hasNew) cols.push(['NEW', newPng, '#1a7f37']);
  const w = COLW * cols.length + GAP * (cols.length + 1);
  const h = HEAD + LBL + Math.max(...cols.map(([, p]) => dh(p))) + GAP;
  let imgs = '';
  cols.forEach(([lbl, png, color], i) => {
    const x = GAP + i * (COLW + GAP);
    imgs += `<text x="${x}" y="${HEAD + 14}" font-size="13" font-weight="700" fill="${color}"
      font-family="Helvetica,Arial,sans-serif">${lbl}</text>
      <image x="${x}" y="${HEAD + LBL}" width="${dw(png)}" height="${dh(png)}"
        href="data:image/png;base64,${b64(png)}"/>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"
    font-family="Helvetica,Arial,sans-serif"><rect width="${w}" height="${h}" fill="#fff"/>
    <text x="${GAP}" y="34" font-size="18" font-weight="700" fill="#1f2328">${title}</text>
    <text x="${GAP}" y="52" font-size="11" fill="#656d76">rendered with @descope/page-editor-components (Descope screen rendering engine) — outlines mark changed components</text>
    ${imgs}</svg>`;
}

(async () => {
  const [oldPath, newPath, outdir, changesPath] = process.argv.slice(2);
  const oldFlow = JSON.parse(fs.readFileSync(oldPath, 'utf8'));
  const newFlow = JSON.parse(fs.readFileSync(newPath, 'utf8'));
  const toMap = (f) => Object.fromEntries((f.screens || []).map((s) => [s.screenId, s.contents]));
  const oldS = toMap(oldFlow), newS = toMap(newFlow);
  let changes = null;
  if (changesPath && fs.existsSync(changesPath)) {
    changes = JSON.parse(fs.readFileSync(changesPath, 'utf8'));
  }
  const wanted = changes ? Object.keys(changes)
    : [...new Set([...Object.keys(oldS), ...Object.keys(newS)])];
  fs.mkdirSync(outdir, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: COLW + 40, height: 1100 },
    deviceScaleFactor: 2 });
  for (const sid of wanted) {
    const o = oldS[sid], n = newS[sid];
    if (!o && !n) continue;
    const hl = changes ? changes[sid] : null;
    const blank = () => { const p = new PNG({ width: COLW * 2, height: 400 }); p.data.fill(255); return p; };
    const oldPng = o ? await shoot(page, screenHtml(o, hl, 'old')) : blank();
    const newPng = n ? await shoot(page, screenHtml(n, hl, 'new')) : blank();
    const svg = composite(oldPng, newPng, `Screen: ${sid}`, !!o, !!n);
    await page.setContent(`<body style="margin:0">${svg}</body>`, { waitUntil: 'networkidle' });
    const el = await page.$('svg');
    fs.writeFileSync(path.join(outdir, `21-pixel-${sid}.png`), await el.screenshot());
    console.log(`21-pixel-${sid}.png`);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });

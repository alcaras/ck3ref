/**
 * The province-raster map engine behind /regions and /regions/<id>.
 *
 * public/map/provinces-index.png encodes one province index per pixel
 * (R = idx & 255, G = idx >> 8). We decode it once into a Uint16Array and
 * from then on the map is data, not a picture: recolouring is a palette swap
 * over 4.7M indices, and hit-testing the cursor is one array lookup.
 *
 * Overlap is the normal case for regions (world_europe contains
 * world_europe_west; the great-holy-war, trade and hunting families cut
 * across everything), so a province covered by k selected regions dithers
 * between their colours through four palettes picked per pixel by
 * ((x>>1) + (y>>1)) & 3, rather than being decided by paint order.
 */

interface MapMeta {
  width: number; height: number; scale: number;
  sourceWidth: number; sourceHeight: number;
  idRanges: [number, number][];
  classNames: string[];
  classes: number[];
  counts: Record<string, number>;
  notDrawn: number[];
  stamped: number[];
  undrawable: number[];
}
interface ProvMeta {
  names: string[]; mapNames: string[];
  terrain: number[]; terrainNames: string[]; terrainLabels: string[];
  terrainColors: string[];
  terrainDefaulted: number[];
}
type TitleRec = { n: string; c?: string; ch?: string[]; p?: number[] };
type GeoTree = Record<'county' | 'duchy' | 'kingdom' | 'empire', Record<string, TitleRec>>;
interface RegionRec {
  i: string; s?: string; n: string; f: string; L?: 1; b?: [number, number, number, number];
  c: number;
  k?: string[]; d?: string[]; y?: string[]; p?: number[]; r?: string[];
  e?: string[]; h?: string[];
}

/** Selection colours. Ours, not the game's — see the legend note on the page. */
const SELECTION = [
  '#b6452c', '#b18d4e', '#6690b8', '#6d9f6a', '#9273b8', '#c39b45',
  '#bc5940', '#97a0a8', '#4c9999', '#c86419', '#8a6fb0', '#7fa87a',
];
const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

/** #rrggbb -> the Uint32 a canvas ImageData wants, which is little-endian ABGR. */
function rgba(hex: string, alpha = 255): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return 0;
  const n = parseInt(m[1], 16);
  return ((alpha << 24) | ((n & 0xff) << 16) | (n & 0xff00) | ((n >> 16) & 0xff)) >>> 0;
}
function rgbaOf(hex: string, fallback: number): number {
  return rgba(hex) || fallback;
}

/** Base-layer colours. Ours: the game paints none of these classes. */
const BASE_COLORS: Record<string, number> = {
  land: rgba('#46342a'), sea: rgba('#161d2a'), lake: rgba('#1e2a3a'),
  river: rgba('#222f40'), impassable: rgba('#1c2023'), wasteland: rgba('#202326'),
  unused: rgba('#13171a'), none: rgba('#0d1217'),
};
const HOVER = rgba('#d3ac63');
const HOVER_WASH = rgba('#d3ac63', 0x99);   // brass wash over the hovered province
const PREVIEW = rgba('#7b6a52');
function darken(c: number, f: number): number {
  const r = ((c & 0xff) * f) | 0;
  const g = (((c >> 8) & 0xff) * f) | 0;
  const b = (((c >> 16) & 0xff) * f) | 0;
  return 0xff000000 | (b << 16) | (g << 8) | r;
}
const esc = (s: string) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));

export async function initRegionMap(root: HTMLElement) {
  const base = root.dataset.base ?? '';
  const canvas = root.querySelector<HTMLCanvasElement>('canvas')!;
  const ctx = canvas.getContext('2d', { alpha: false })!;
  const statusEl = root.querySelector<HTMLElement>('[data-map-status]')!;
  const tipEl = root.querySelector<HTMLElement>('[data-map-tip]')!;
  const legendEl = root.querySelector<HTMLElement>('[data-map-legend]');
  const rowsHost = document.querySelector<HTMLElement>('[data-region-list]');
  const urlState = root.dataset.url === 'yes';

  const j = (f: string) => fetch(`${base}/map/${f}`).then((r) => {
    if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`);
    return r.json();
  });

  let meta: MapMeta, pmeta: ProvMeta, tree: GeoTree, regionList: RegionRec[];
  let idx: Uint16Array;
  statusEl.textContent = 'Loading the province raster (3072×1536, one province index per pixel)…';
  try {
    const [m, pm, gt, rl, bitmap] = await Promise.all([
      j('map-meta.json'), j('provinces-meta.json'), j('geo-tree.json'),
      j('regions-membership.json'), loadRaster(`${base}/map/provinces-index.png`),
    ]);
    meta = m; pmeta = pm; tree = gt; regionList = rl;
    idx = decodeIndices(bitmap, m.width, m.height);
  } catch (err) {
    statusEl.textContent = `Map data failed to load (${(err as Error).message}). ` +
      'The region list and every composition table below are unaffected.';
    return;
  }

  const W = meta.width, H = meta.height;
  const defaultedTerrain = new Set(pmeta.terrainDefaulted);

  // ---- lookup tables ----------------------------------------------------
  const ids: number[] = [0];
  for (const [a, b] of meta.idRanges) for (let p = a; p <= b; p++) ids.push(p);
  const N = ids.length - 1;
  const denseOf = new Map<number, number>();
  for (let d = 1; d <= N; d++) denseOf.set(ids[d], d);

  const classOf = new Uint8Array(N + 1);
  for (let d = 1; d <= N; d++) classOf[d] = meta.classes[d - 1];

  // de jure chain, as dense-index -> title index per tier
  const tiers = ['county', 'duchy', 'kingdom', 'empire'] as const;
  const keys: Record<string, string[]> = {};
  const pos: Record<string, Map<string, number>> = {};
  for (const t of tiers) {
    keys[t] = Object.keys(tree[t]);
    pos[t] = new Map(keys[t].map((k, i) => [k, i]));
  }
  const countyOf = new Int32Array(N + 1).fill(-1);
  keys.county.forEach((c, ci) => {
    for (const pid of tree.county[c].p ?? []) {
      const d = denseOf.get(pid);
      if (d !== undefined) countyOf[d] = ci;
    }
  });
  const parentOf: Record<string, Int32Array> = {};
  for (const [child, parent] of [['county', 'duchy'], ['duchy', 'kingdom'],
    ['kingdom', 'empire']] as const) {
    const arr = new Int32Array(keys[child].length).fill(-1);
    keys[parent].forEach((pk, pi) => {
      for (const ck of tree[parent][pk].ch ?? []) {
        const ci = pos[child].get(ck);
        if (ci !== undefined) arr[ci] = pi;
      }
    });
    parentOf[child] = arr;
  }
  const duchyOfDense = (d: number) => (countyOf[d] < 0 ? -1 : parentOf.county[countyOf[d]]);

  // ---- regions ----------------------------------------------------------
  const regionOf = new Map<string, RegionRec>();
  for (const r of regionList) regionOf.set(r.i, r);

  const provincesOfTitle = (tier: typeof tiers[number], key: string): number[] => {
    const rec = tree[tier][key];
    if (!rec) return [];
    if (tier === 'county') return rec.p ?? [];
    const child = tier === 'duchy' ? 'county' : tier === 'kingdom' ? 'duchy' : 'kingdom';
    const out: number[] = [];
    for (const k of rec.ch ?? []) out.push(...provincesOfTitle(child, k));
    return out;
  };

  const resolved = new Map<string, Int32Array>();
  function resolveRegion(id: string, stack: Set<string> = new Set()): Int32Array {
    const cached = resolved.get(id);
    if (cached) return cached;
    const r = regionOf.get(id);
    if (!r || stack.has(id)) return new Int32Array(0);
    stack.add(id);
    const set = new Set<number>();
    const add = (pid: number) => {
      const d = denseOf.get(pid);
      if (d !== undefined) set.add(d);
    };
    for (const pid of r.p ?? []) add(pid);
    for (const c of r.y ?? []) provincesOfTitle('county', c).forEach(add);
    for (const d of r.d ?? []) provincesOfTitle('duchy', d).forEach(add);
    for (const k of r.k ?? []) provincesOfTitle('kingdom', k).forEach(add);
    for (const e of r.e ?? []) provincesOfTitle('empire', e).forEach(add);
    for (const sub of r.r ?? []) for (const d of resolveRegion(sub, stack)) set.add(d);
    stack.delete(id);
    const arr = Int32Array.from(set).sort();
    resolved.set(id, arr);
    return arr;
  }

  // province -> the regions containing it, as one flat CSR index (612 regions
  // x ~520 provinces = 320k pairs; a Map of arrays would cost far more).
  const regionIdx: string[] = regionList.map((r) => r.i);
  let revStart: Int32Array, revData: Int32Array;
  {
    const counts = new Int32Array(N + 2);
    const all: Int32Array[] = regionIdx.map((id) => resolveRegion(id));
    for (const arr of all) for (const d of arr) counts[d + 1]++;
    for (let i = 1; i <= N + 1; i++) counts[i] += counts[i - 1];
    revStart = counts;
    revData = new Int32Array(counts[N + 1]);
    const fill = Int32Array.from(counts);
    all.forEach((arr, ri) => { for (const d of arr) revData[fill[d]++] = ri; });
  }
  const regionsAt = (d: number) => {
    const out: number[] = [];
    for (let i = revStart[d]; i < revStart[d + 1]; i++) out.push(revData[i]);
    return out;
  };

  // ---- palettes ---------------------------------------------------------
  const basePalettes: Record<string, Uint32Array> = {};
  function buildBase(kind: string): Uint32Array {
    const pal = new Uint32Array(N + 1);
    pal[0] = BASE_COLORS.none;
    const terrCol = pmeta.terrainColors.map((c) => rgbaOf(c, BASE_COLORS.land));
    // de jure tiers paint each title's own `color` from landed_titles
    const dejure = kind === 'duchy' || kind === 'kingdom' || kind === 'empire'
      ? keys[kind].map((k) => rgbaOf(tree[kind][k].c ?? '', BASE_COLORS.land))
      : null;
    for (let d = 1; d <= N; d++) {
      const cname = meta.classNames[classOf[d]];
      const fallback = BASE_COLORS[cname] ?? BASE_COLORS.land;
      if (kind === 'terrain') {
        const t = pmeta.terrain[d - 1];
        pal[d] = t >= 0 ? terrCol[t] : fallback;
      } else if (dejure) {
        let ti = duchyOfDense(d);
        if (kind !== 'duchy' && ti >= 0) ti = parentOf.duchy[ti];
        if (kind === 'empire' && ti >= 0) ti = parentOf.kingdom[ti];
        pal[d] = ti >= 0 ? dejure[ti] : fallback;
      } else {
        pal[d] = fallback;
      }
    }
    return pal;
  }
  const baseFor = (kind: string) => (basePalettes[kind] ??= buildBase(kind));

  // ---- view -------------------------------------------------------------
  const view = { x: 0, y: 0, scale: 1 };
  const off = document.createElement('canvas');
  off.width = W; off.height = H;
  const offCtx = off.getContext('2d', { alpha: false })!;
  const image = offCtx.createImageData(W, H);
  const pixels = new Uint32Array(image.data.buffer);

  let selected: string[] = [];
  let preview: string | null = null;
  let hovered = 0;
  let pinned = 0;
  let baseKind = 'plain';
  let overlapCount = 0;
  let crowded = 0;   // provinces in more selected regions than the 4 palettes can show

  function repaint() {
    const bp = baseFor(baseKind);
    const pal = [new Uint32Array(bp), new Uint32Array(bp), new Uint32Array(bp),
      new Uint32Array(bp)];
    overlapCount = 0;
    crowded = 0;
    if (selected.length) {
      const colorOf = new Map<string, number>();
      selected.forEach((id, i) => colorOf.set(id, rgbaOf(SELECTION[i % SELECTION.length], HOVER)));
      const selSet = new Set(selected);
      for (let d = 1; d <= N; d++) {
        let hits: number[] | null = null;
        for (let i = revStart[d]; i < revStart[d + 1]; i++) {
          const id = regionIdx[revData[i]];
          if (selSet.has(id)) (hits ??= []).push(colorOf.get(id)!);
        }
        if (!hits) continue;
        if (hits.length > 1) overlapCount++;
        if (hits.length > 4) crowded++;
        for (let k = 0; k < 4; k++) pal[k][d] = hits[k % hits.length];
      }
    }
    if (preview && !selected.includes(preview)) {
      for (const d of resolveRegion(preview)) for (let k = 0; k < 4; k++) pal[k][d] = PREVIEW;
    }
    // one pass: palette + de jure borders (county faint, duchy stronger)
    for (let y = 0; y < H; y++) {
      const row = y * W;
      const ph = y >> 1;
      const below = y + 1 < H ? row + W : row;
      for (let x = 0; x < W; x++) {
        const i = row + x;
        const d = idx[i];
        let c = pal[((x >> 1) + ph) & 3][d];
        const right = idx[x + 1 < W ? i + 1 : i];
        const down = idx[below + x];
        if (right !== d || down !== d) {
          const cd = countyOf[d];
          const rd = countyOf[right], dd = countyOf[down];
          if (cd !== rd || cd !== dd) {
            const du = cd < 0 ? -1 : parentOf.county[cd];
            const ru = rd < 0 ? -1 : parentOf.county[rd];
            const dn = dd < 0 ? -1 : parentOf.county[dd];
            c = darken(c, du !== ru || du !== dn ? 0.45 : 0.74);
          }
        }
        pixels[i] = c;
      }
    }
    offCtx.putImageData(image, 0, 0);
    blit();
    updateLegend();
  }

  function blit() {
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
    }
    const sw = cw / view.scale, sh = ch / view.scale;
    // When the viewport is wider or taller than the map at this zoom, centre
    // the map in the spare space instead of pinning it to a corner.
    view.x = sw >= W ? (W - sw) / 2 : clamp(view.x, 0, W - sw);
    view.y = sh >= H ? (H - sh) / 2 : clamp(view.y, 0, H - sh);
    ctx.imageSmoothingEnabled = false;   // indices must never be resampled
    ctx.fillStyle = '#17120d';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(off, view.x, view.y, sw, sh, 0, 0, canvas.width, canvas.height);
    drawHot(cw, ch);
  }

  // The hovered/pinned province is washed in over the blit rather than baked
  // into the palette: a palette change costs a 4.7M-pixel repaint, while this
  // pass is one loop over the ~0.5M pixels actually on screen.
  const hotCv = document.createElement('canvas');
  const hotCx = hotCv.getContext('2d')!;
  let hotImg: ImageData | null = null;
  let hotPix: Uint32Array | null = null;
  function drawHot(cw: number, ch: number) {
    const hot = pinned || hovered;
    if (!hot || cw < 1 || ch < 1) return;
    if (hotCv.width !== cw || hotCv.height !== ch) {
      hotCv.width = cw; hotCv.height = ch;
      hotImg = hotCx.createImageData(cw, ch);
      hotPix = new Uint32Array(hotImg.data.buffer);
    }
    hotPix!.fill(0);
    const inv = 1 / view.scale;
    let any = false;
    for (let dy = 0; dy < ch; dy++) {
      const sy = (view.y + dy * inv) | 0;
      if (sy < 0 || sy >= H) continue;
      const row = sy * W;
      const out = dy * cw;
      for (let dx = 0; dx < cw; dx++) {
        const sx = (view.x + dx * inv) | 0;
        if (sx < 0 || sx >= W) continue;
        if (idx[row + sx] === hot) { hotPix![out + dx] = HOVER_WASH; any = true; }
      }
    }
    if (!any) return;
    hotCx.putImageData(hotImg!, 0, 0);
    ctx.drawImage(hotCv, 0, 0, canvas.width, canvas.height);
  }

  // Repaints are coalesced: sweeping the region list fires one preview change
  // per row, and only the last one before the frame matters.
  let pending = 0;
  function queueRepaint() {
    if (pending) return;
    pending = requestAnimationFrame(() => { pending = 0; repaint(); });
  }

  function fit(box: [number, number, number, number] | null) {
    const cw = canvas.clientWidth || 1, ch = canvas.clientHeight || 1;
    if (!box) {
      view.scale = Math.min(cw / W, ch / H);
      view.x = 0; view.y = 0;
      blit();
      return;
    }
    const [x0, y0, x1, y1] = box;
    const bw = Math.max(8, x1 - x0 + 1), bh = Math.max(8, y1 - y0 + 1);
    view.scale = clamp(Math.min(cw / bw, ch / bh) * 0.92, Math.min(cw / W, ch / H), 24);
    view.x = (x0 + x1) / 2 - cw / view.scale / 2;
    view.y = (y0 + y1) / 2 - ch / view.scale / 2;
    blit();
  }

  function selectionBox(): [number, number, number, number] | null {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const id of selected) {
      const b = regionOf.get(id)?.b;
      if (!b) continue;
      x0 = Math.min(x0, b[0]); y0 = Math.min(y0, b[1]);
      x1 = Math.max(x1, b[2]); y1 = Math.max(y1, b[3]);
    }
    return x1 < 0 ? null : [x0, y0, x1, y1];
  }

  // ---- tooltip ----------------------------------------------------------
  const titleLink = (tier: typeof tiers[number], i: number): string => {
    if (i < 0) return '';
    const key = keys[tier][i];
    const rec = tree[tier][key];
    let empire = -1;
    if (tier === 'empire') empire = i;
    else if (tier === 'kingdom') empire = parentOf.kingdom[i];
    else if (tier === 'duchy') { const k = parentOf.duchy[i]; empire = k < 0 ? -1 : parentOf.kingdom[k]; }
    else { const du = parentOf.county[i]; const k = du < 0 ? -1 : parentOf.duchy[du]; empire = k < 0 ? -1 : parentOf.kingdom[k]; }
    const name = esc(rec.n);
    if (empire < 0) return `<span>${name}</span>`;
    const page = keys.empire[empire];
    const href = `${base}/titles/${page}${page === key ? '' : `#${key}`}`;
    return `<a href="${href}">${name}</a>`;
  };

  function describe(d: number): string {
    const pid = ids[d];
    const name = pmeta.names[d - 1];
    const mapName = pmeta.mapNames[d - 1];
    const cname = meta.classNames[classOf[d]];
    const ci = countyOf[d];
    const di = ci < 0 ? -1 : parentOf.county[ci];
    const ki = di < 0 ? -1 : parentOf.duchy[di];
    const ei = ki < 0 ? -1 : parentOf.kingdom[ki];
    const t = pmeta.terrain[d - 1];
    const defaulted = t >= 0 && defaultedTerrain.has(d);

    const chain = [
      ci >= 0 ? titleLink('county', ci) : '',
      di >= 0 ? titleLink('duchy', di) : '',
      ki >= 0 ? titleLink('kingdom', ki) : '',
      ei >= 0 ? titleLink('empire', ei) : '',
    ].filter(Boolean);

    const here = regionsAt(d);
    const chips = here.map((ri) => {
      const r = regionList[ri];
      const on = selected.includes(r.i);
      return `<button class="rchip${on ? ' is-on' : ''}" data-toggle="${esc(r.i)}"` +
        ` title="${esc(r.i)} · ${r.c} provinces">${esc(r.n)}` +
        `${r.L ? '' : '<i class="rkey">key</i>'}</button>`;
    }).join('');

    return (
      `<div class="tip-h"><b>${name ? esc(name) : (mapName ? esc(mapName) : 'unnamed province')}</b>` +
      `<span class="tip-id">#${pid}</span></div>` +
      (name ? '' : mapName
        ? `<div class="tip-sub">no localized name — <code>${esc(mapName)}</code> is the internal map name</div>`
        : '<div class="tip-sub">no name in the game files</div>') +
      `<div class="tip-sub">${esc(cname)}${t >= 0
        ? ` · <span title="${esc(pmeta.terrainNames[t])}">${esc(pmeta.terrainLabels[t])}</span>` +
          `${defaulted ? ' <i class="tip-dim">(the game’s default_land, not a row of its own)</i>' : ''}`
        : ''}</div>` +
      (chain.length ? `<div class="tip-chain">${chain.join('<span class="sep">›</span>')}</div>` : '') +
      `<div class="tip-rh">${here.length} region${here.length === 1 ? '' : 's'} contain this province` +
      `${here.length ? ' — click to toggle' : ''}</div>` +
      (here.length ? `<div class="tip-chips">${chips}</div>` : '')
    );
  }

  function showTip(d: number, clientX: number, clientY: number) {
    if (!d) { if (!pinned) tipEl.hidden = true; return; }
    tipEl.innerHTML = describe(d);
    tipEl.hidden = false;
    const box = root.getBoundingClientRect();
    const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
    tipEl.style.left = `${clamp(clientX - box.left + 14, 4, Math.max(4, box.width - tw - 4))}px`;
    tipEl.style.top = `${clamp(clientY - box.top + 14, 4, Math.max(4, box.height - th - 4))}px`;
  }

  function updateLegend() {
    if (!legendEl) return;
    if (!selected.length) {
      legendEl.innerHTML = '<span class="lg-empty">No region selected — tick one in the list, ' +
        'or click a province and use its chips.</span>';
      return;
    }
    const items = selected.map((id, i) => {
      const r = regionOf.get(id);
      return `<span class="lg-item"><i class="lg-sw" style="--c:${SELECTION[i % SELECTION.length]}"></i>` +
        `<a href="${base}/regions/${esc(r?.s ?? r?.i ?? id)}">${esc(r?.n ?? id)}</a>` +
        `<b>${r ? r.c : 0}</b>` +
        `<button class="lg-x" data-toggle="${esc(id)}" title="remove">×</button></span>`;
    }).join('');
    const overlapNote = selected.length > 1
      ? `<span class="lg-note">${overlapCount.toLocaleString()} province${overlapCount === 1 ? '' : 's'} ` +
        'covered by more than one — shown dithered between their colours.' +
        (crowded ? ` The dither carries four colours at most, so ${crowded.toLocaleString()} ` +
          'province' + (crowded === 1 ? ' that sits' : 's that sit') +
          ' in more than four of these show only four — hover one for its full list.' : '') +
        '</span>'
      : '';
    legendEl.innerHTML = items + overlapNote;
  }

  // ---- selection --------------------------------------------------------
  function setRowState() {
    if (!rowsHost) return;
    for (const box of rowsHost.querySelectorAll<HTMLInputElement>('input[data-region]')) {
      const id = box.dataset.region!;
      const i = selected.indexOf(id);
      box.checked = i >= 0;
      const row = box.closest<HTMLElement>('.rrow');
      if (row) row.style.setProperty('--c', i >= 0 ? SELECTION[i % SELECTION.length] : 'transparent');
    }
  }

  function toggle(id: string, on?: boolean) {
    if (!regionOf.has(id)) return;
    const at = selected.indexOf(id);
    const want = on ?? at < 0;
    if (want && at < 0) selected.push(id);
    else if (!want && at >= 0) selected.splice(at, 1);
    else return;
    setRowState();
    repaint();
    if (pinned) showTipInPlace();
    syncUrl();
  }

  function showTipInPlace() {
    if (pinned) { tipEl.innerHTML = describe(pinned); tipEl.hidden = false; }
  }

  function syncUrl() {
    if (!urlState) return;
    const q: string[] = [];
    if (selected.length) q.push(`r=${selected.map(encodeURIComponent).join(',')}`);
    if (baseKind !== 'plain') q.push(`base=${baseKind}`);
    history.replaceState(null, '', location.pathname + (q.length ? `?${q.join('&')}` : ''));
  }

  // ---- events -----------------------------------------------------------
  const atEvent = (ev: { clientX: number; clientY: number }) => {
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(view.x + (ev.clientX - rect.left) / view.scale);
    const y = Math.floor(view.y + (ev.clientY - rect.top) / view.scale);
    if (x < 0 || y < 0 || x >= W || y >= H) return 0;
    return idx[y * W + x];
  };

  let dragging = false, moved = false, dragFrom = { x: 0, y: 0, vx: 0, vy: 0 };
  canvas.addEventListener('pointerdown', (ev) => {
    dragging = true; moved = false;
    dragFrom = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y };
    canvas.setPointerCapture(ev.pointerId);
  });
  canvas.addEventListener('pointermove', (ev) => {
    if (dragging) {
      const dx = ev.clientX - dragFrom.x, dy = ev.clientY - dragFrom.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true;
      view.x = dragFrom.vx - dx / view.scale;
      view.y = dragFrom.vy - dy / view.scale;
      blit();
      return;
    }
    const d = atEvent(ev);
    if (d !== hovered) {
      hovered = d;
      if (!pinned) blit();
    }
    if (!pinned) showTip(d, ev.clientX, ev.clientY);
  });
  canvas.addEventListener('pointerup', (ev) => {
    dragging = false;
    canvas.releasePointerCapture(ev.pointerId);
    if (moved) return;
    const d = atEvent(ev);
    pinned = d && d === pinned ? 0 : d;
    hovered = d;
    blit();
    if (pinned) showTip(pinned, ev.clientX, ev.clientY); else tipEl.hidden = true;
  });
  canvas.addEventListener('pointerleave', () => {
    if (pinned) return;
    hovered = 0; tipEl.hidden = true; blit();
  });
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const px = view.x + (ev.clientX - rect.left) / view.scale;
    const py = view.y + (ev.clientY - rect.top) / view.scale;
    const min = Math.min(canvas.clientWidth / W, canvas.clientHeight / H);
    view.scale = clamp(view.scale * (ev.deltaY < 0 ? 1.2 : 1 / 1.2), min, 24);
    view.x = px - (ev.clientX - rect.left) / view.scale;
    view.y = py - (ev.clientY - rect.top) / view.scale;
    blit();
  }, { passive: false });

  root.addEventListener('click', (ev) => {
    const btn = (ev.target as Element).closest<HTMLElement>('[data-toggle]');
    if (btn) { ev.preventDefault(); toggle(btn.dataset.toggle!); return; }
    const act = (ev.target as Element).closest<HTMLElement>('[data-map-action]');
    if (!act) return;
    if (act.dataset.mapAction === 'world') fit(null);
    if (act.dataset.mapAction === 'selection') fit(selectionBox());
    if (act.dataset.mapAction === 'clear') { selected = []; setRowState(); repaint(); syncUrl(); }
  });
  for (const sel of root.querySelectorAll<HTMLSelectElement>('[data-map-base]')) {
    sel.addEventListener('change', () => { baseKind = sel.value; repaint(); syncUrl(); });
  }

  if (rowsHost) {
    rowsHost.addEventListener('change', (ev) => {
      const box = (ev.target as HTMLElement).closest<HTMLInputElement>('input[data-region]');
      if (box) {
        toggle(box.dataset.region!, box.checked);
        if (box.checked) fit(regionOf.get(box.dataset.region!)?.b ?? null);
      }
    });
    rowsHost.addEventListener('pointerover', (ev) => {
      const row = (ev.target as HTMLElement).closest<HTMLElement>('.rrow');
      const id = row?.dataset.regionRow ?? null;
      if (id !== preview) { preview = id; queueRepaint(); }
    });
    rowsHost.addEventListener('pointerleave', () => {
      if (preview) { preview = null; queueRepaint(); }
    });
    const search = document.querySelector<HTMLInputElement>('[data-region-search]');
    const countEl = document.querySelector<HTMLElement>('[data-region-count]');
    const famSel = document.querySelector<HTMLSelectElement>('[data-region-family]');
    const filter = () => {
      const q = (search?.value ?? '').trim().toLowerCase();
      const fam = famSel?.value ?? '';
      let shown = 0;
      for (const row of rowsHost.querySelectorAll<HTMLElement>('.rrow')) {
        const ok = (!q || (row.dataset.search ?? '').includes(q)) &&
          (!fam || row.dataset.family === fam);
        row.hidden = !ok;
        if (ok) shown++;
      }
      for (const g of rowsHost.querySelectorAll<HTMLElement>('[data-family-group]')) {
        g.hidden = ![...g.querySelectorAll('.rrow')].some((r) => !(r as HTMLElement).hidden);
      }
      if (countEl) countEl.textContent = `${shown} of ${regionList.length}`;
    };
    search?.addEventListener('input', filter);
    famSel?.addEventListener('change', filter);
    filter();
  }

  window.addEventListener('resize', blit);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && pinned) { pinned = 0; tipEl.hidden = true; blit(); }
  });

  // ---- boot -------------------------------------------------------------
  const preselect = (root.dataset.preselect ?? '').split(',').filter(Boolean);
  const fromUrl = urlState
    ? (new URLSearchParams(location.search).get('r') ?? '').split(',').filter(Boolean)
    : [];
  selected = [...new Set([...preselect, ...fromUrl])].filter((id) => regionOf.has(id));
  if (urlState) {
    const b = new URLSearchParams(location.search).get('base');
    if (b && ['plain', 'terrain', 'duchy', 'kingdom', 'empire'].includes(b)) {
      baseKind = b;
      for (const sel of root.querySelectorAll<HTMLSelectElement>('[data-map-base]')) sel.value = b;
    }
  }
  statusEl.hidden = true;
  canvas.hidden = false;
  setRowState();
  fit(selected.length ? selectionBox() : null);
  repaint();
}

async function loadRaster(url: string): Promise<ImageData> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`raster: HTTP ${res.status}`);
  const bitmap = await createImageBitmap(await res.blob());
  const c = document.createElement('canvas');
  c.width = bitmap.width; c.height = bitmap.height;
  const cx = c.getContext('2d', { alpha: false, willReadFrequently: true })!;
  cx.imageSmoothingEnabled = false;
  cx.drawImage(bitmap, 0, 0);
  return cx.getImageData(0, 0, bitmap.width, bitmap.height);
}

function decodeIndices(image: ImageData, w: number, h: number): Uint16Array {
  if (image.width !== w || image.height !== h) {
    throw new Error(`raster is ${image.width}x${image.height}, meta says ${w}x${h}`);
  }
  const src = image.data;
  const out = new Uint16Array(w * h);
  for (let i = 0, p = 0; i < out.length; i++, p += 4) out[i] = src[p] | (src[p + 1] << 8);
  return out;
}

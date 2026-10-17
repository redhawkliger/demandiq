/* Signal Flow motion kit — live traffic simulations for page backgrounds and corner widgets.
   SignalFlow.intersection(canvas, opts)  -> 4-leg signalized intersection (NEMA 2/6 main, 4/8 side)
   SignalFlow.corridor(canvas, opts)      -> scrolling time-space diagram of a coordinated corridor
   Both return an api with .destroy() to stop the animation (call it on React unmount).
   Colors come from CSS tokens: --road --road-verge --paint --paint-yellow --car
   --lamp-go --lamp-amber --lamp-stop --lamp-off (intersection) and --fg --muted --line --go --amber --stop (corridor). */
(function (global) {
  'use strict';
  var reduced = function () { return global.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; };
  function tok(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fb;
  }
  // Signal plan: intervals [['g',40],['y',4],['r',28]] + offset (s). Returns t -> {state, left, cycle}
  function plan(intervals, offset) {
    var C = intervals.reduce(function (a, b) { return a + b[1]; }, 0);
    return function (t) {
      var p = (((t - (offset || 0)) % C) + C) % C, acc = 0;
      for (var i = 0; i < intervals.length; i++) {
        acc += intervals[i][1];
        if (p < acc) return { state: intervals[i][0], left: acc - p, cycle: C };
      }
      return { state: 'r', left: 0, cycle: C };
    };
  }
  // One travel lane with simple car-following and stop-line logic
  function Lane(o) {
    for (var k in o) this[k] = o[k];
    this.cars = []; this.spawnIn = Math.random() * this.headway;
  }
  Lane.prototype.step = function (dt, t, rec) {
    this.spawnIn -= dt;
    if (this.spawnIn <= 0) {
      var last = this.cars[this.cars.length - 1];
      if (!last || last.s - last.len > this.gap * 2) {
        this.cars.push({ s: 0, v: this.vmax * (0.85 + Math.random() * 0.15), len: this.carLen * (0.85 + Math.random() * 0.45),
          shade: 0.7 + Math.random() * 0.3, brake: false, hist: [], id: Math.random() });
      }
      this.spawnIn = this.headway * (0.45 + Math.random() * 1.1);
    }
    for (var i = 0; i < this.cars.length; i++) {
      var c = this.cars[i], gap = Infinity;
      if (i > 0) { var L = this.cars[i - 1]; gap = L.s - L.len - c.s - this.gap; }
      for (var j = 0; j < this.stops.length; j++) {
        var st = this.stops[j], d = st.s - c.s;
        if (d < -0.5) continue;
        var sig = st.plan(t).state;
        if (sig !== 'g') {
          var clears = sig === 'y' && d < c.v * 1.1;
          if (!clears) gap = Math.min(gap, d - 1);
        }
        break;
      }
      var vt = Math.min(this.vmax, Math.sqrt(2 * this.dec * Math.max(0, gap)));
      var dv = vt - c.v;
      c.brake = dv < -this.dec * 0.15 * dt * 60 || (c.v < 1 && gap < 6);
      c.v += dv > 0 ? Math.min(dv, this.acc * dt) : Math.max(dv, -this.dec * 2.2 * dt);
      if (c.v < 0) c.v = 0;
      c.s += c.v * dt;
      if (rec && (!c.hist.length || t - c.hist[c.hist.length - 1][0] >= rec)) c.hist.push([t, c.s]);
    }
    var len = this.length;
    this.cars = this.cars.filter(function (c) { return c.s - c.len < len + 40; });
  };

  function fit(canvas) {
    var r = canvas.getBoundingClientRect(), dpr = Math.min(global.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    var ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, W: r.width, H: r.height };
  }
  function loop(tick) {
    var last = performance.now(), raf = 0, run = true;
    function f(now) { var dt = Math.min(0.05, (now - last) / 1000); last = now; tick(dt); if (run) raf = requestAnimationFrame(f); }
    raf = requestAnimationFrame(f);
    function vis() { last = performance.now(); }
    document.addEventListener('visibilitychange', vis);
    return function () { run = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', vis); };
  }
  // Redraw when the page theme changes (data-theme attribute or OS light/dark). Returns an unsubscribe function.
  function watchTheme(fn) {
    var mo = new MutationObserver(fn);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
    var mq = global.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
    if (mq) mq.addEventListener('change', fn);
    return function () { mo.disconnect(); if (mq) mq.removeEventListener('change', fn); };
  }
  function rr(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h);
    ctx.fill();
  }

  /* ---------- Intersection ---------- */
  function intersection(canvas, opts) {
    opts = opts || {};
    var speed = opts.speed || 3, LW = 16, HALF = 32, SET = 15;
    var mainPlan = plan(opts.mainPlan || [['g', 40], ['y', 4], ['r', 28]], 0);
    var sidePlan = plan(opts.sidePlan || [['r', 46], ['g', 20], ['y', 4], ['r', 2]], 0);
    var g, lanes, cx, cy, t = 0, colors;
    function readColors() {
      colors = { road: tok('--road', '#22282E'), verge: tok('--road-verge', '#171B1F'), paint: tok('--paint', '#E9E4D4'),
        yellow: tok('--paint-yellow', '#F2C230'), car: tok('--car', '#B9C3CC'), go: tok('--lamp-go', '#1EE39A'),
        amber: tok('--lamp-amber', '#FFB020'), stop: tok('--lamp-stop', '#FF4438'), off: tok('--lamp-off', '#2A3138') };
    }
    function build() {
      g = fit(canvas); cx = Math.round(g.W * (opts.crossAt || 0.62)); cy = Math.round(g.H / 2);
      var W = g.W, H = g.H, mk = function (o) { return new Lane(o); };
      var main = { vmax: 46, acc: 16, dec: 30, carLen: 13, gap: 5, headway: opts.mainHeadway || 2.1 };
      var side = { vmax: 34, acc: 14, dec: 28, carLen: 12, gap: 5, headway: opts.sideHeadway || 4.2 };
      function L(base, o) { var x = {}; for (var k in base) x[k] = base[k]; for (k in o) x[k] = o[k]; return mk(x); }
      lanes = [
        L(main, { axis: 'h', dir: 1, off: cy + 8, length: W, stops: [{ s: cx - HALF - SET, plan: mainPlan }] }),
        L(main, { axis: 'h', dir: 1, off: cy + 24, length: W, stops: [{ s: cx - HALF - SET, plan: mainPlan }] }),
        L(main, { axis: 'h', dir: -1, off: cy - 8, length: W, stops: [{ s: W - cx - HALF - SET, plan: mainPlan }] }),
        L(main, { axis: 'h', dir: -1, off: cy - 24, length: W, stops: [{ s: W - cx - HALF - SET, plan: mainPlan }] }),
        L(side, { axis: 'v', dir: 1, off: cx + 8, length: H, stops: [{ s: H - cy - HALF - SET, plan: sidePlan }] }),
        L(side, { axis: 'v', dir: 1, off: cx + 24, length: H, stops: [{ s: H - cy - HALF - SET, plan: sidePlan }] }),
        L(side, { axis: 'v', dir: -1, off: cx - 8, length: H, stops: [{ s: cy - HALF - SET, plan: sidePlan }] }),
        L(side, { axis: 'v', dir: -1, off: cx - 24, length: H, stops: [{ s: cy - HALF - SET, plan: sidePlan }] })
      ];
      readColors();
    }
    function dash(ctx, x1, y1, x2, y2, on, offd) {
      ctx.setLineDash([on, offd]); ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.setLineDash([]);
    }
    function head(ctx, x, y, state) {
      ctx.fillStyle = '#07090B'; rr(ctx, x, y, 9, 25, 2.5);
      var order = ['r', 'y', 'g'], col = { r: colors.stop, y: colors.amber, g: colors.go };
      for (var i = 0; i < 3; i++) {
        var on = order[i] === state;
        ctx.fillStyle = on ? col[order[i]] : colors.off;
        ctx.shadowColor = on ? col[order[i]] : 'transparent'; ctx.shadowBlur = on ? 12 : 0;
        ctx.beginPath(); ctx.arc(x + 4.5, y + 5 + i * 7.5, 2.7, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0;
    }
    function draw() {
      var ctx = g.ctx, W = g.W, H = g.H, ms = mainPlan(t).state, ss = sidePlan(t).state;
      ctx.fillStyle = colors.verge; ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = colors.road; ctx.fillRect(0, cy - HALF, W, HALF * 2); ctx.fillRect(cx - HALF, 0, HALF * 2, H);
      ctx.strokeStyle = colors.paint; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.2;
      [cy - 16, cy + 16].forEach(function (y) { dash(ctx, 0, y, cx - HALF - 14, y, 10, 10); dash(ctx, cx + HALF + 14, y, W, y, 10, 10); });
      [cx - 16, cx + 16].forEach(function (x) { dash(ctx, x, 0, x, cy - HALF - 14, 8, 9); dash(ctx, x, cy + HALF + 14, x, H, 8, 9); });
      ctx.globalAlpha = 0.9; ctx.strokeStyle = colors.yellow; ctx.lineWidth = 1;
      [cy - 1.5, cy + 1.5].forEach(function (y) { dash(ctx, 0, y, cx - HALF - 14, y, 1, 0); dash(ctx, cx + HALF + 14, y, W, y, 1, 0); });
      [cx - 1.5, cx + 1.5].forEach(function (x) { dash(ctx, x, 0, x, cy - HALF - 14, 1, 0); dash(ctx, x, cy + HALF + 14, x, H, 1, 0); });
      // stop bars + crosswalks
      ctx.globalAlpha = 0.8; ctx.fillStyle = colors.paint;
      ctx.fillRect(cx - HALF - SET, cy, 2.5, HALF); ctx.fillRect(cx + HALF + SET - 2.5, cy - HALF, 2.5, HALF);
      ctx.fillRect(cx, cy + HALF + SET - 2.5, HALF, 2.5); ctx.fillRect(cx - HALF, cy - HALF - SET, HALF, 2.5);
      ctx.globalAlpha = 0.35;
      for (var k = -HALF + 2; k < HALF; k += 6) {
        ctx.fillRect(cx - HALF - 12, cy + k, 9, 3); ctx.fillRect(cx + HALF + 3, cy + k, 9, 3);
        ctx.fillRect(cx + k, cy - HALF - 12, 3, 9); ctx.fillRect(cx + k, cy + HALF + 3, 3, 9);
      }
      ctx.globalAlpha = 1;
      // vehicles
      lanes.forEach(function (ln) {
        ln.cars.forEach(function (c) {
          var front, back, a = ln.axis === 'h';
          if (a) { front = ln.dir > 0 ? c.s : W - c.s; back = front - ln.dir * c.len; }
          else { front = ln.dir > 0 ? H - c.s : c.s; back = front + (ln.dir > 0 ? c.len : -c.len); }
          var lo = Math.min(front, back), w = Math.abs(front - back), th = 8.5;
          ctx.globalAlpha = c.shade; ctx.fillStyle = colors.car;
          if (a) rr(ctx, lo, ln.off - th / 2, w, th, 2); else rr(ctx, ln.off - th / 2, lo, th, w, 2);
          ctx.globalAlpha = 1;
          // headlights
          ctx.fillStyle = '#FFF4CF';
          var fd = a ? (ln.dir > 0 ? -1.5 : 1.5) : (ln.dir > 0 ? 1.5 : -1.5);
          if (a) { ctx.fillRect(front + fd - 0.8, ln.off - 3.3, 1.6, 1.6); ctx.fillRect(front + fd - 0.8, ln.off + 1.7, 1.6, 1.6); }
          else { ctx.fillRect(ln.off - 3.3, front + fd - 0.8, 1.6, 1.6); ctx.fillRect(ln.off + 1.7, front + fd - 0.8, 1.6, 1.6); }
          if (c.brake) {
            ctx.fillStyle = colors.stop; ctx.shadowColor = colors.stop; ctx.shadowBlur = 8;
            var bd = -fd;
            if (a) { ctx.fillRect(back + bd - 0.9, ln.off - 3.5, 1.8, 2); ctx.fillRect(back + bd - 0.9, ln.off + 1.5, 1.8, 2); }
            else { ctx.fillRect(ln.off - 3.5, back + bd - 0.9, 2, 1.8); ctx.fillRect(ln.off + 1.5, back + bd - 0.9, 2, 1.8); }
            ctx.shadowBlur = 0;
          }
        });
      });
      head(ctx, cx - HALF - SET - 14, cy + HALF + 6, ms);
      head(ctx, cx + HALF + SET + 5, cy - HALF - 31, ms);
      head(ctx, cx + HALF + 6, cy + HALF + SET + 3, ss);
      head(ctx, cx - HALF - 15, cy - HALF - SET - 28, ss);
    }
    function step(dt) { t += dt; lanes.forEach(function (l) { l.step(dt, t); }); }
    build();
    for (var i = 0; i < 600; i++) step(0.05); // warm start so the first frame already has traffic
    draw();
    var ro = new ResizeObserver(function () { var keep = t; build(); t = keep; for (var j = 0; j < 300; j++) step(0.05); draw(); });
    ro.observe(canvas);
    var unwatch = watchTheme(function () { readColors(); draw(); });
    var api = { main: function () { return mainPlan(t); }, side: function () { return sidePlan(t); } };
    var stop = null;
    if (!reduced()) stop = loop(function (dt) { step(dt * speed); draw(); if (opts.onTick) opts.onTick(api); });
    else if (opts.onTick) opts.onTick(api);
    api.destroy = function () { if (stop) stop(); ro.disconnect(); unwatch(); };
    return api;
  }

  /* ---------- Corridor time-space diagram ---------- */
  function corridor(canvas, opts) {
    opts = opts || {};
    var speed = opts.speed || 4, LEN = opts.length || 1000, WIN = opts.window || 170;
    var sigs = (opts.signals || [{ s: 250, off: 0 }, { s: 550, off: 20 }, { s: 850, off: 40 }]).map(function (x, i) {
      return { s: x.s, name: x.name || 'S' + (i + 1), plan: plan(opts.intervals || [['g', 30], ['y', 4], ['r', 26]], x.off) };
    });
    var lane = new Lane({ vmax: 15, acc: 2, dec: 3.2, carLen: 5, gap: 2.5, headway: opts.headway || 6.5, length: LEN, stops: sigs });
    var g, t = 0, done = [], colors;
    function readColors() {
      colors = { fg: tok('--fg', '#E6EAEE'), muted: tok('--muted', '#8C98A4'), line: tok('--line', '#28313A'),
        g: tok('--go', '#1EE39A'), y: tok('--amber', '#FFB020'), r: tok('--stop', '#FF5A4E') };
    }
    function step(dt) {
      t += dt; lane.step(dt, t, 0.5);
      // keep trajectories of vehicles that left, until they scroll out of the window
      lane.cars.forEach(function (c) { if (c.s > LEN - 1 && !c.out) { c.out = true; done.push(c); } });
      done = done.filter(function (c) { return c.hist.length && c.hist[c.hist.length - 1][0] > t - WIN; });
    }
    function draw() {
      var ctx = g.ctx, W = g.W, H = g.H, padL = 22, padB = 4, pw = W - padL, ph = H - padB - 4;
      ctx.clearRect(0, 0, W, H);
      var X = function (tt) { return padL + pw - ((t - tt) / WIN) * pw; };
      var Y = function (s) { return 4 + ph - (s / LEN) * ph; };
      ctx.font = '600 9px "Overpass Mono", ui-monospace, monospace'; ctx.textBaseline = 'middle';
      sigs.forEach(function (sg) {
        var y = Y(sg.s);
        ctx.fillStyle = colors.muted; ctx.fillText(sg.name, 0, y);
        for (var tt = t - WIN; tt < t; tt += 0.5) {
          ctx.fillStyle = colors[sg.plan(tt).state];
          ctx.globalAlpha = sg.plan(tt).state === 'g' ? 0.9 : 0.75;
          ctx.fillRect(X(tt), y - 1.5, pw / WIN * 0.5 + 0.6, 3);
        }
        ctx.globalAlpha = 1;
      });
      ctx.strokeStyle = colors.fg; ctx.lineWidth = 1.1; ctx.lineJoin = 'round';
      lane.cars.concat(done).forEach(function (c) {
        var h = c.hist; if (h.length < 2) return;
        ctx.globalAlpha = 0.42; ctx.beginPath();
        var started = false;
        for (var i = 0; i < h.length; i++) {
          if (h[i][0] < t - WIN) continue;
          var px = X(h[i][0]), py = Y(Math.min(h[i][1], LEN));
          if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
        }
        if (!c.out) ctx.lineTo(X(t), Y(c.s));
        ctx.stroke();
      });
      ctx.globalAlpha = 1;
      lane.cars.forEach(function (c) {
        ctx.fillStyle = c.brake ? colors.r : colors.fg;
        ctx.beginPath(); ctx.arc(X(t), Y(c.s), 1.8, 0, Math.PI * 2); ctx.fill();
      });
    }
    g = fit(canvas); readColors();
    for (var i = 0; i < WIN * 4; i++) step(0.25);
    draw();
    var ro = new ResizeObserver(function () { g = fit(canvas); draw(); });
    ro.observe(canvas);
    var unwatch = watchTheme(function () { readColors(); draw(); });
    var api = { signal: function (i) { return sigs[i || 0].plan(t); }, signals: sigs };
    var stop = null;
    if (!reduced()) stop = loop(function (dt) { step(dt * speed); draw(); if (opts.onTick) opts.onTick(api); });
    else if (opts.onTick) opts.onTick(api);
    api.destroy = function () { if (stop) stop(); ro.disconnect(); unwatch(); };
    return api;
  }

  global.SignalFlow = { plan: plan, Lane: Lane, intersection: intersection, corridor: corridor };
})(window);

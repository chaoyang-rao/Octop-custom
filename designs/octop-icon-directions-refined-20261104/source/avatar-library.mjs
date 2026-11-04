/* Original Octop geometric avatars. Geometry, expression and motion are authored
 * here; no artwork or implementation from another product is embedded. */
export const SHAPES = Object.freeze([
  { id: "blob", name: "圆形", mood: "安静", motion: "轻呼吸 · 双眨眼" },
  { id: "pebble", name: "六边形", mood: "好奇", motion: "左右张望 · 单眨轻跳" },
  { id: "squircle", name: "圆方", mood: "专注", motion: "眯眼思考 · 轻偏头" },
  { id: "droplet", name: "椭圆", mood: "腼腆", motion: "探头 · 害羞眨眼" },
  { id: "cloud", name: "五边形", mood: "开心", motion: "轻轻漂浮 · 笑眼" },
  { id: "star", name: "八边形", mood: "兴奋", motion: "蓄力跳起 · 摇摆" },
  { id: "triangle", name: "三角", mood: "沉稳", motion: "缓慢环顾 · 点头" },
  { id: "diamond", name: "菱形", mood: "自信", motion: "抬头示意 · 俏皮眨眼" },
  { id: "capsule", name: "胶囊", mood: "灵动", motion: "左右摇摆 · 轻快回望" },
]);
export const COLORS = Object.freeze([
  { id: "ink", name: "曜黑", hex: "#000000" },
  { id: "jade", name: "青绿", hex: "#54B9A6" },
  { id: "blue", name: "晴蓝", hex: "#3B82F6" },
  { id: "violet", name: "鸢紫", hex: "#835BD6" },
  { id: "rose", name: "莓粉", hex: "#EB4698" },
  { id: "amber", name: "金橙", hex: "#F19D38" },
  { id: "coral", name: "暖橙", hex: "#ED702D" },
  { id: "cocoa", name: "可可", hex: "#8C6640" },
  { id: "red", name: "朱红", hex: "#E75B66" },
]);
const shapeIds = new Set(SHAPES.map((x) => x.id));
const colorIds = new Set(COLORS.map((x) => x.id));
export const validShape = (id) => shapeIds.has(id);
export const validColor = (id) => colorIds.has(id);
export const getColor = (id) => COLORS.find((x) => x.id === id) || COLORS[0];
// Tight but motion-safe framing: the whole six-second motion remains visible.
export const VIEWBOXES = Object.freeze({
  blob: "40 40 432 432",
  pebble: "28 24 456 456",
  squircle: "48 56 416 416",
  droplet: "40 48 432 432",
  cloud: "32 32 448 448",
  star: "28 16 456 456",
  triangle: "56 64 400 400",
  diamond: "32 40 448 448",
  capsule: "40 56 432 400",
});
const TAU = Math.PI * 2;
const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
const smooth = (v) => {
  v = clamp(v);
  return v * v * (3 - 2 * v);
};
const windowAt = (t, from, to, ramp = 0.25) =>
  smooth((t - from) / ramp) * smooth((to - t) / ramp);
const pulse = (t, center, width) =>
  Math.abs(t - center) < width / 2
    ? (1 + Math.cos((TAU * (t - center)) / width)) / 2
    : 0;
const blinkAt = (t, events) =>
  Math.max(0, ...events.map(([at, width]) => pulse(t, at, width)));
const lerp = (a, b, t) => a + (b - a) * t;

function roundedPolygon(vertices, rounding = 0.24, steps = 7) {
  const out = [];
  for (let i = 0; i < vertices.length; i++) {
    const v = vertices[i],
      p = vertices[(i - 1 + vertices.length) % vertices.length],
      n = vertices[(i + 1) % vertices.length];
    const a = [lerp(v[0], p[0], rounding), lerp(v[1], p[1], rounding)];
    const b = [lerp(v[0], n[0], rounding), lerp(v[1], n[1], rounding)];
    for (let j = 0; j <= steps; j++) {
      const u = j / steps;
      out.push([
        (1 - u) ** 2 * a[0] + 2 * u * (1 - u) * v[0] + u * u * b[0],
        (1 - u) ** 2 * a[1] + 2 * u * (1 - u) * v[1] + u * u * b[1],
      ]);
    }
  }
  return out;
}
// Keep persisted IDs while replacing the old organic silhouettes with symmetry.
const regularPolygon = (sides, radius, offset = -Math.PI / 2) =>
  roundedPolygon(
    Array.from({ length: sides }, (_, i) => {
      const angle = offset + (i * TAU) / sides;
      return [Math.cos(angle) * radius, Math.sin(angle) * radius];
    }),
    0.1,
    8,
  );
const pebble = regularPolygon(6, 198, -Math.PI / 6);
const triangle = roundedPolygon(
  [
    [0, -191],
    [186, 145],
    [-186, 145],
  ],
  0.18,
  14,
);
const star = regularPolygon(8, 197, Math.PI / 8);
const cloud = regularPolygon(5, 201);
const diamond = roundedPolygon(
  [
    [0, -213],
    [203, 0],
    [0, 213],
    [-203, 0],
  ],
  0.1,
  12,
);
function bodyPoints(shape) {
  if (shape === "pebble") return pebble;
  if (shape === "triangle") return triangle;
  if (shape === "star") return star;
  if (shape === "cloud") return cloud;
  if (shape === "diamond") return diamond;
  const out = [];
  for (let i = 0; i < 96; i++) {
    const a = (i * TAU) / 96;
    if (shape === "squircle") {
      const c = Math.cos(a),
        s = Math.sin(a);
      out.push([
        174 * Math.sign(c) * Math.abs(c) ** 0.53,
        168 * Math.sign(s) * Math.abs(s) ** 0.53,
      ]);
    } else if (shape === "droplet") {
      out.push([157 * Math.cos(a), 188 * Math.sin(a)]);
    } else if (shape === "capsule") {
      const c = Math.cos(a);
      out.push([28 * Math.sign(c) + 162 * c, 162 * Math.sin(a)]);
    } else {
      out.push([182 * Math.cos(a), 182 * Math.sin(a)]);
    }
  }
  return out;
}
function eyePoints(cx, cy, diameter, open = 1, smile = 0) {
  const rx = diameter / 2,
    ry = Math.max(2, (diameter * open) / 2);
  // Equal radii when open: a round eye. Lids compress during a blink.
  return Array.from({ length: 40 }, (_, i) => {
    const a = (i * TAU) / 40,
      x = Math.cos(a) * rx;
    return [cx + x, cy + Math.sin(a) * ry - smile * (1 - (x / rx) ** 2)];
  });
}
export function avatarFrame(shape = "blob", color = "ink", seconds = 0) {
  shape = validShape(shape) ? shape : "blob";
  const base = getColor(color).hex,
    t = ((seconds % 6) + 6) % 6,
    p = (t * TAU) / 6;
  let rot = 0,
    sx = 1,
    sy = 1,
    dy = 0,
    gx = 0,
    gy = 0,
    faceX = 0,
    faceY = -30,
    diameter = 56,
    openL = 1,
    openR = 1,
    smile = 0;
  const b = Math.sin(p);
  if (shape === "blob") {
    const look = windowAt(t, 2.15, 3.65, 0.35),
      back = windowAt(t, 4.9, 5.7, 0.22);
    rot = -4.5 + 2.2 * b + 4.1 * look;
    sx = 1 + 0.013 * b;
    sy = 1 + 0.017 * b;
    dy = 3 * b;
    faceX = 38;
    faceY = -55;
    gx = 10 * look - 4 * back;
    gy = -4 * look;
    openL = openR =
      1 -
      blinkAt(t, [
        [1.26, 0.24],
        [1.62, 0.21],
        [4.5, 0.25],
      ]);
  } else if (shape === "pebble") {
    const l = windowAt(t, 0.4, 1.65, 0.3),
      r = windowAt(t, 3.2, 4.35, 0.3),
      u = (t - 2.12) / 0.86;
    const jump = u > 0 && u < 1 ? Math.sin(Math.PI * u) ** 2 : 0,
      squash = 0.065 * pulse(t, 2.04, 0.32) + 0.055 * pulse(t, 3.03, 0.28);
    rot = 3.5 + 3.1 * b - 3.8 * l + 4 * r;
    sx = 1 + 0.014 * b + squash * 0.7 - jump * 0.018;
    sy = 1 + 0.014 * b - squash + jump * 0.035;
    dy = 2 * b - 23 * jump;
    faceX = 24;
    faceY = -48;
    gx = -11 * l + 9 * r;
    gy = -3 * jump + 2 * l;
    openL =
      1 -
      blinkAt(t, [
        [0.98, 0.23],
        [4.95, 0.24],
      ]);
    openR = Math.min(openL, 1 - pulse(t, 3.76, 0.38));
  } else if (shape === "squircle") {
    const think = windowAt(t, 2.05, 3.3, 0.4),
      look = windowAt(t, 3.8, 5.25, 0.35);
    rot = -2 + 5 * look;
    sx = 1 + 0.006 * b;
    sy = 1 + 0.008 * b;
    dy = 1.5 * b;
    gx = 6 * look;
    gy = 5 * think;
    faceY = -25;
    openL = openR =
      1 -
      0.65 * think -
      blinkAt(t, [
        [0.8, 0.25],
        [4.95, 0.23],
      ]) *
        (1 - 0.65 * think);
    smile = 1.8 * think;
  } else if (shape === "droplet") {
    const shy = windowAt(t, 1.35, 3.55, 0.45),
      peek = windowAt(t, 3.9, 5.35, 0.3);
    rot = -5 - 7 * shy + 4 * peek;
    dy = 4 * b + 4 * shy;
    sx = 1 + 0.01 * b;
    sy = 1 + 0.018 * b;
    faceY = 15;
    faceX = -8;
    gx = -11 * shy + 7 * peek;
    gy = 4 * shy;
    diameter = 55;
    openL =
      1 -
      blinkAt(t, [
        [0.75, 0.3],
        [3.3, 0.36],
      ]);
    openR = Math.min(openL, 1 - pulse(t, 4.65, 0.34));
  } else if (shape === "cloud") {
    const happy = windowAt(t, 2.15, 3.3, 0.3);
    rot = 2.2 * Math.sin(p);
    dy = 8 * Math.sin(p) + 3 * Math.sin(2 * p);
    sx = 1 + 0.015 * b;
    sy = 1 + 0.01 * b;
    faceY = 9;
    diameter = 55;
    gx = 7 * Math.sin(p);
    gy = -2;
    openL = openR =
      (1 - 0.78 * happy) *
      (1 -
        blinkAt(t, [
          [1.05, 0.25],
          [4.8, 0.25],
        ]));
    smile = 8 * happy;
  } else if (shape === "star") {
    const u = (t - 1.8) / 1.18,
      jump = u > 0 && u < 1 ? Math.sin(Math.PI * u) ** 2 : 0,
      anticipate = pulse(t, 1.69, 0.34),
      land = pulse(t, 3.05, 0.3);
    rot = 6 * Math.sin(p) + 11 * jump * Math.sin(((t - 1.8) * TAU) / 1.18);
    dy = -31 * jump + 3 * b;
    sx = 1 + anticipate * 0.05 + land * 0.04 - jump * 0.02;
    sy = 1 - anticipate * 0.07 - land * 0.055 + jump * 0.05;
    faceY = 0;
    diameter = 58;
    gx = 8 * Math.sin(p);
    gy = -6 * jump;
    openL = openR =
      1 -
      blinkAt(t, [
        [0.6, 0.18],
        [0.88, 0.17],
        [4.4, 0.22],
      ]);
  } else if (shape === "diamond") {
    const greet = windowAt(t, 1.35, 2.55, 0.3),
      glance = windowAt(t, 3.6, 4.9, 0.35);
    rot = 3 * b - 4 * greet;
    dy = -7 * greet + 2 * b;
    faceY = -18;
    gx = 9 * glance;
    gy = -5 * greet;
    openL =
      1 -
      blinkAt(t, [
        [0.8, 0.24],
        [5.3, 0.26],
      ]);
    openR = Math.min(openL, 1 - pulse(t, 2.05, 0.32));
  } else if (shape === "capsule") {
    const glance = windowAt(t, 2.8, 4.25, 0.4);
    rot = 5 * b;
    dy = -6 * pulse(t, 1.7, 0.7) + 2 * b;
    faceY = -12;
    gx = 12 * b - 9 * glance;
    gy = -3 * glance;
    openL = openR =
      1 -
      blinkAt(t, [
        [1.15, 0.22],
        [4.7, 0.27],
      ]);
  } else {
    const nod = 4 * pulse(t, 2.1, 0.52) + 3 * pulse(t, 2.83, 0.48),
      look = windowAt(t, 3.6, 5.3, 0.5);
    rot = -2 + 3 * look;
    dy = nod + 1.5 * b;
    sx = 1 + 0.005 * b;
    sy = 1 + 0.008 * b;
    faceY = 20;
    diameter = 54;
    gx = 8 * look;
    gy = nod * 0.8;
    openL = openR =
      1 -
      blinkAt(t, [
        [1, 0.32],
        [4.7, 0.36],
      ]);
  }
  // A shared tilted pose and upper-right gaze; retain each character's lids,
  // smiles, glances and body motion. The triangle needs its wider lower face.
  rot -= 9;
  faceX = shape === "triangle" ? 16 : 30 + faceX * 0.15;
  faceY = shape === "triangle" ? 8 : -54 + faceY * 0.15;
  gx *= 0.65;
  gy *= 0.65;
  const angle = (rot * Math.PI) / 180,
    tx = (points) =>
      points.map(([x, y]) => {
        x *= sx;
        y *= sy;
        return [
          256 + x * Math.cos(angle) - y * Math.sin(angle),
          264 + dy + x * Math.sin(angle) + y * Math.cos(angle),
        ];
      });
  const body = tx(bodyPoints(shape));
  // 100 px between eye centers (v2 was 71–73): visibly wider spacing.
  const eyes = [
    tx(eyePoints(faceX - 50 + gx, faceY + gy, diameter, clamp(openL), smile)),
    tx(
      eyePoints(faceX + 50 + gx, faceY - 3 + gy, diameter, clamp(openR), smile),
    ),
  ];
  return {
    shape,
    color: getColor(color).id,
    base,
    outline: base,
    body,
    eyes,
    facets: [],
  };
}
export const pathData = (points) =>
  "M" +
  points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join("L") +
  "Z";

export function avatarUrl(shape, color = "ink") {
  return validShape(shape)
    ? `/expert-avatars/v2/${shape}-${getColor(color).id}.svg`
    : null;
}
export function parseAvatarUrl(url) {
  if (typeof url !== "string") return null;
  const match = url.match(
    /^\/expert-avatars\/v[12]\/([a-z]+)-([a-z]+)\.svg(?:[?#].*)?$/,
  );
  return match && validShape(match[1]) && validColor(match[2])
    ? { shape: match[1], color: match[2] }
    : null;
}
function luminance(hex) {
  const a = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
}
export function contrast(a, b) {
  const x = luminance(a),
    y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
export function bubbleStyle(color = "ink") {
  const hex = getColor(color).hex,
    dark = "#0B101B";
  const foreground =
    contrast(hex, "#FFFFFF") >= contrast(hex, dark) ? "#FFFFFF" : dark;
  return {
    backgroundColor: hex,
    color: foreground,
    "--expert-bubble-bg": hex,
    "--expert-bubble-fg": foreground,
  };
}

export function createExpertAvatars({ React }) {
  const h = React.createElement;
  // One clock for all visible avatars, capped at 25 fps. Unmounted/hidden views
  // unsubscribe; reduced-motion users receive the exact static initial pose.
  const listeners = new Set();
  let raf = 0,
    last = 0;
  function tick(now) {
    if (now - last >= 40) {
      last = now;
      for (const cb of listeners) cb(now / 1000);
    }
    raf = listeners.size && !document.hidden ? requestAnimationFrame(tick) : 0;
  }
  function start() {
    if (!raf && listeners.size && !document.hidden)
      raf = requestAnimationFrame(tick);
  }
  function subscribe(cb) {
    listeners.add(cb);
    start();
    return () => {
      listeners.delete(cb);
      if (!listeners.size && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
  }
  if (typeof document !== "undefined")
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else start();
    });
  function Avatar({
    shape = "blob",
    color = "ink",
    size = 32,
    className,
    style,
    static: still = false,
    title,
    ...rest
  }) {
    const [time, setTime] = React.useState(0),
      ref = React.useRef(null),
      id = React.useId().replace(/:/g, "");
    React.useEffect(() => {
      const media = window.matchMedia("(prefers-reduced-motion: reduce)");
      let off = () => {},
        visible = true;
      const update = () => {
        off();
        off = () => {};
        if (!still && !media.matches && visible) off = subscribe(setTime);
        else setTime(0);
      };
      const observer =
        typeof IntersectionObserver === "function"
          ? new IntersectionObserver(([entry]) => {
              visible = entry.isIntersecting;
              update();
            })
          : null;
      if (ref.current) observer?.observe(ref.current);
      media.addEventListener("change", update);
      update();
      return () => {
        off();
        observer?.disconnect();
        media.removeEventListener("change", update);
      };
    }, [shape, still]);
    const f = avatarFrame(shape, color, time),
      clip = `oa-${id}`;
    const name = SHAPES.find((x) => x.id === f.shape)?.name || "圆形";
    return h(
      "svg",
      {
        ref,
        width: size,
        height: size,
        viewBox: VIEWBOXES[f.shape],
        className,
        style: {
          display: "inline-block",
          width: size,
          height: size,
          flexShrink: 0,
          verticalAlign: "middle",
          overflow: "visible",
          ...style,
        },
        role: "img",
        "aria-label": title || `${name} · ${getColor(color).name}`,
        focusable: "false",
        ...rest,
      },
      h(
        "defs",
        null,
        h("clipPath", { id: clip }, h("path", { d: pathData(f.body) })),
      ),
      h("path", {
        "data-avatar-body": "",
        d: pathData(f.body),
        fill: f.base,
        stroke: f.outline,
        strokeWidth: 1.2,
        strokeLinejoin: "round",
      }),
      ...f.facets.map((part, i) =>
        h("path", {
          key: `facet${i}`,
          d: pathData(part.points),
          fill: part.fill,
          clipPath: `url(#${clip})`,
        }),
      ),
      ...f.eyes.map((points, i) =>
        h("path", { key: `eye${i}`, d: pathData(points), fill: "#FFFDF7" }),
      ),
    );
  }
  const MemoAvatar = React.memo(Avatar);
  const renderAvatar = (props) => h(MemoAvatar, props);
  function ShapeColorPicker({
    shape,
    color,
    onShapeChange,
    onColorChange,
    disabled = false,
  }) {
    const selectedColor = getColor(color);
    return h(
      "div",
      { className: "oa-picker" },
      h(
        "div",
        { className: "oa-picker-label" },
        "头像形状",
        h("span", null, "每种形状都有自己的神态和动作"),
      ),
      h(
        "div",
        { className: "oa-shapes", "aria-label": "头像形状" },
        ...SHAPES.map((s) =>
          h(
            "button",
            {
              key: s.id,
              type: "button",
              className: "oa-shape",
              "aria-pressed": shape === s.id,
              disabled,
              title: `${s.name} · ${s.mood} · ${s.motion}`,
              onClick: () => onShapeChange?.(s.id),
            },
            renderAvatar({ shape: s.id, color: selectedColor.id, size: 80 }),
            h("span", { className: "oa-shape-name" }, s.name),
            h("span", { className: "oa-shape-mood" }, s.mood),
          ),
        ),
      ),
      h(
        "div",
        { className: "oa-picker-label" },
        "头像颜色",
        h("span", null, selectedColor.name),
      ),
      h(
        "div",
        { className: "oa-colors", "aria-label": "头像颜色" },
        ...COLORS.map((c) =>
          h(
            "button",
            {
              key: c.id,
              type: "button",
              className: "oa-color",
              "aria-label": `${c.name} ${c.hex}`,
              "aria-pressed": selectedColor.id === c.id,
              disabled,
              title: c.name,
              onClick: () => {
                if (!validShape(shape)) onShapeChange?.("blob");
                onColorChange?.(c.id);
              },
            },
            h(
              "span",
              {
                className: "oa-swatch",
                style: {
                  backgroundColor: c.hex,
                  color: bubbleStyle(c.id).color,
                },
              },
              selectedColor.id === c.id ? "✓" : "",
            ),
            h("span", null, c.name),
          ),
        ),
      ),
    );
  }
  function Picker({ shape, color, onChange, ...rest }) {
    return h(ShapeColorPicker, {
      shape,
      color,
      ...rest,
      onShapeChange: (s) => onChange?.({ shape: s, color: getColor(color).id }),
      onColorChange: (c) =>
        onChange?.({ shape: validShape(shape) ? shape : "blob", color: c }),
    });
  }
  return {
    Avatar: MemoAvatar,
    Picker,
    ShapeColorPicker,
    renderAvatar,
    SHAPES,
    COLORS,
    parseAvatarUrl,
    avatarUrl,
    bubbleStyle,
    validShape,
    validColor,
  };
}

export function animatedSvg(shape, color) {
  const count = 75,
    frames = Array.from({ length: count + 1 }, (_, i) =>
      avatarFrame(shape, color, (i * 6) / count),
    );
  const a = frames[0],
    timing = 'dur="6s" repeatCount="indefinite" calcMode="linear"';
  const animation = (values) =>
    `<animate attributeName="d" values="${values.join(";")}" ${timing}/>`;
  const animated = (name, selector, fill, extra = "") =>
    `<path id="${name}" d="${pathData(
      selector(a),
    )}" fill="${fill}" ${extra}>${animation(
      frames.map((f) => pathData(selector(f))),
    )}</path>`;
  const staticParts = () =>
    `<path d="${pathData(a.body)}" fill="${a.base}" stroke="${
      a.outline
    }" stroke-width="1.2"/>` +
    a.facets
      .map(
        (part) =>
          `<path d="${pathData(part.points)}" fill="${
            part.fill
          }" clip-path="url(#still-clip)"/>`,
      )
      .join("") +
    a.eyes.map((eye) => `<path d="${pathData(eye)}" fill="#FFFDF7"/>`).join("");
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="${
      VIEWBOXES[shape] || VIEWBOXES.blob
    }" role="img" aria-label="${SHAPES.find((x) => x.id === shape)?.name} · ${
      getColor(color).name
    }">` +
    `<style>.still{display:none}@media(prefers-reduced-motion:reduce){.motion{display:none}.still{display:inline}}</style>` +
    `<defs><clipPath id="clip">${animated(
      "clip-body",
      (f) => f.body,
      "#fff",
    )}</clipPath><clipPath id="still-clip"><path d="${pathData(
      a.body,
    )}"/></clipPath></defs>` +
    `<g class="motion">${animated(
      "body",
      (f) => f.body,
      a.base,
      `stroke="${a.outline}" stroke-width="1.2" stroke-linejoin="round"`,
    )}${a.facets
      .map((part, i) =>
        animated(
          `facet${i}`,
          (f) => f.facets[i].points,
          part.fill,
          'clip-path="url(#clip)"',
        ),
      )
      .join("")}${[0, 1]
      .map((i) => animated(`eye${i}`, (f) => f.eyes[i], "#FFFDF7"))
      .join("")}</g>` +
    `<g class="still">${staticParts()}</g></svg>`
  );
}

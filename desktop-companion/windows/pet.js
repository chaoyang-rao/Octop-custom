"use strict";
const canvas = document.querySelector("canvas"),
  ctx = canvas.getContext("2d", { willReadFrequently: true });
let model = null,
  images = {},
  state = { animation: "idle", facingLeft: false, phase: "rest" },
  epoch = performance.now(),
  dragging = false;
const invoke = (op, args) => window.companionNative.invoke(op, args);
async function load() {
  const result = await invoke("petModel");
  if (!result) return;
  model = result.manifest;
  images = {};
  await Promise.all(
    Object.entries(result.images).map(async ([name, src]) => {
      const img = new Image();
      img.src = src;
      await img.decode();
      images[name] = img;
    }),
  );
}
function paintImage(name, rect) {
  if (images[name]) ctx.drawImage(images[name], ...rect);
}
function draw(now) {
  const ratio = window.devicePixelRatio || 1,
    width = innerWidth,
    height = innerHeight;
  if (
    canvas.width !== Math.round(width * ratio) ||
    canvas.height !== Math.round(height * ratio)
  ) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  if (model) {
    if (state.edge && state.collapsed) drawPeek(width, height);
    else {
      const phase = state.phase || "rest",
        name =
          phase === "rest"
            ? state.animation
            : phase === "flying"
            ? "dragging"
            : phase;
      const animation = model.animations[name] || model.animations.idle,
        elapsed = now - epoch;
      const frames = animation.frames,
        index =
          Math.floor(elapsed / (animation.frameDelay * 1000)) % frames.length;
      const frame = frames[index],
        base = animation.baseFrame || frame;
      const seconds = elapsed / 1000,
        lift =
          phase === "takeoff"
            ? 0.7 * Math.sin((Math.min(1, seconds / 0.32) * Math.PI) / 2)
            : phase === "flying"
            ? 0.65 + 0.2 * Math.sin(seconds * 6)
            : phase === "landing"
            ? 0.85 * Math.exp(-12 * seconds) * Math.cos(19 * seconds)
            : 0;
      ctx.save();
      ctx.translate(0, -lift * Math.min(2.5, height * 0.015));
      if (state.facingLeft) {
        ctx.translate(2 * model.registration.anchor[0] * width, 0);
        ctx.scale(-1, 1);
      }
      const rect = model.registration.frames[base] || [0, 0, 1, 1],
        destination = [
          rect[0] * width,
          rect[1] * height,
          rect[2] * width,
          rect[3] * height,
        ];
      paintImage(base, destination);
      if (animation.baseFrame && frame !== base && animation.overlayRect) {
        const [x, y, w, h] = animation.overlayRect;
        ctx.save();
        ctx.beginPath();
        ctx.rect(x * width, y * height, w * width, h * height);
        ctx.clip();
        paintImage(frame, destination);
        ctx.restore();
      }
      ctx.restore();
    }
  }
  requestAnimationFrame(draw);
}
function drawPeek(w, h) {
  const side = state.edge === "left" || state.edge === "right",
    peek = model.peek[side ? "right" : "bottom"],
    img = images[peek.frame];
  if (!img) return;
  const [x, y, cw, ch] = peek.crop;
  ctx.save();
  if (state.edge === "left" || state.edge === "top") {
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
  }
  if (state.edge === "top") {
    ctx.translate(0, h);
    ctx.scale(1, -1);
  }
  const image = () =>
    ctx.drawImage(
      img,
      x * img.width,
      y * img.height,
      cw * img.width,
      ch * img.height,
      0,
      0,
      w,
      h,
    );
  const grips = peek.gripRects || [];
  ctx.save();
  ctx.beginPath();
  ctx.rect(-w, -h, w * 3, h * 3);
  for (const [gx, gy, gw, gh] of grips)
    ctx.ellipse(
      ((gx + gw / 2 - x) / cw) * w,
      ((gy + gh / 2 - y) / ch) * h,
      ((gw / cw) * w) / 2,
      ((gh / ch) * h) / 2,
      0,
      0,
      Math.PI * 2,
    );
  ctx.clip("evenodd");
  const pivot = peek.pivot || [0.5, 0.5],
    px = ((pivot[0] - x) / cw) * w,
    py = ((pivot[1] - y) / ch) * h;
  ctx.translate(px, py);
  ctx.rotate((-(peek.rotation || 0) * Math.PI) / 180);
  ctx.translate(-px, -py);
  ctx.translate(
    side ? w * (peek.retraction || 0) : 0,
    side ? 0 : h * (peek.retraction || 0),
  );
  image();
  ctx.restore();
  for (const [gx, gy, gw, gh] of grips) {
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(
      ((gx + gw / 2 - x) / cw) * w,
      ((gy + gh / 2 - y) / ch) * h,
      ((gw / cw) * w) / 2,
      ((gh / ch) * h) / 2,
      0,
      0,
      Math.PI * 2,
    );
    ctx.clip();
    image();
    ctx.restore();
  }
  ctx.restore();
}
window.companionNative.onEvent((event) => {
  if (event.type === "petReload") void load();
  if (event.type === "petState") {
    if (
      event.data.phase !== state.phase ||
      event.data.animation !== state.animation
    )
      epoch = performance.now();
    state = event.data;
  }
  if (event.type === "hitTest") {
    const { x, y } = event.data,
      r = devicePixelRatio || 1;
    let hit = false;
    if (x >= 0 && y >= 0 && x < innerWidth && y < innerHeight)
      hit =
        ctx.getImageData(Math.floor(x * r), Math.floor(y * r), 1, 1).data[3] >
        20;
    void invoke("petHit", { hit });
  }
});
canvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  dragging = true;
  canvas.setPointerCapture(event.pointerId);
  void invoke("petDragStart");
});
canvas.addEventListener("pointerup", () => {
  if (dragging) {
    dragging = false;
    void invoke("petDragEnd");
  }
});
canvas.addEventListener("pointercancel", () => {
  dragging = false;
  void invoke("petDragEnd");
});
canvas.addEventListener("dblclick", () => void invoke("showChat"));
canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  void invoke("petMenu");
});
void load();
requestAnimationFrame(draw);

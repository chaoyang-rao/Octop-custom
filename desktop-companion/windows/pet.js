"use strict";
const canvas = document.querySelector("canvas"),
  ctx = canvas.getContext("2d", { willReadFrequently: true });
const pixels = document.createElement("canvas"),
  source = pixels.getContext("2d");
const invoke = (op, args) => window.companionNative.invoke(op, args);
let dragging = false,
  press = null;
function paint(frame) {
  const { width, height, rgba } = frame;
  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width < 1 ||
    height < 1 ||
    width > 1024 ||
    height > 1024 ||
    rgba.length !== width * height * 4
  )
    return;
  pixels.width = width;
  pixels.height = height;
  source.putImageData(
    new ImageData(new Uint8ClampedArray(rgba), width, height),
    0,
    0,
  );
  canvas.width = Math.round(innerWidth * devicePixelRatio);
  canvas.height = Math.round(innerHeight * devicePixelRatio);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(pixels, 0, 0, canvas.width, canvas.height);
}
window.companionNative.onEvent((event) => {
  if (event.type === "petFrame") paint(event.data);
  if (event.type === "petReload")
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (event.type === "hitTest") {
    const { x, y } = event.data,
      ratio = devicePixelRatio || 1;
    const hit =
      x >= 0 &&
      y >= 0 &&
      x < innerWidth &&
      y < innerHeight &&
      ctx.getImageData(Math.floor(x * ratio), Math.floor(y * ratio), 1, 1)
        .data[3] > 20;
    void invoke("petHit", { hit });
  }
});
canvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  press = { x: event.clientX, y: event.clientY };
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener("pointermove", (event) => {
  if (
    press &&
    !dragging &&
    Math.hypot(event.clientX - press.x, event.clientY - press.y) >= 4
  ) {
    dragging = true;
    void invoke("petDragStart");
  }
  if (!dragging) {
    const fit = Math.min((innerWidth - 6) / 360, (innerHeight - 6) / 320);
    void invoke("petHover", {
      x: (event.clientX - (innerWidth - fit * 360) / 2) / fit,
      y: (event.clientY - (innerHeight - fit * 320) / 2) / fit,
    });
  }
});
const release = () => {
  press = null;
  if (dragging) {
    dragging = false;
    void invoke("petDragEnd");
  }
};
canvas.addEventListener("pointerup", release);
canvas.addEventListener("pointercancel", release);
canvas.addEventListener(
  "pointerleave",
  () => void invoke("petHover", { x: -1, y: -1 }),
);
canvas.addEventListener("dblclick", () => void invoke("showChat"));
canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  void invoke("petMenu");
});

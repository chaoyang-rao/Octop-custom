"use strict";
function clamp(n, a, b) {
  return Math.max(a, Math.min(b, n));
}
function fullFrame(old, side, area) {
  return {
    x: Math.round(
      clamp(
        old.x + old.width / 2 - side / 2,
        area.x,
        area.x + area.width - side,
      ),
    ),
    y: Math.round(
      clamp(old.y + old.height - side, area.y, area.y + area.height - side),
    ),
    width: Math.round(side),
    height: Math.round(side),
  };
}
function dock(frame, area, displays) {
  const cx = frame.x + frame.width / 2,
    cy = frame.y + frame.height / 2;
  const choices = [
    ["left", Math.abs(frame.x - area.x), { x: area.x - 2, y: cy }],
    [
      "right",
      Math.abs(frame.x + frame.width - area.x - area.width),
      { x: area.x + area.width + 2, y: cy },
    ],
    ["top", Math.abs(frame.y - area.y), { x: cx, y: area.y - 2 }],
    [
      "bottom",
      Math.abs(frame.y + frame.height - area.y - area.height),
      { x: cx, y: area.y + area.height + 2 },
    ],
  ];
  const adjacent = (p) =>
    displays.some(
      (d) =>
        p.x >= d.x && p.x < d.x + d.width && p.y >= d.y && p.y < d.y + d.height,
    );
  return (
    choices
      .filter(
        ([, distance, p]) =>
          distance <= Math.max(16, Math.min(30, frame.width * 0.16)) &&
          !adjacent(p),
      )
      .sort((a, b) => a[1] - b[1])[0]?.[0] || null
  );
}
function peekFrame(full, area, edge, peek, registration) {
  const factor = (full.width * registration.headWidth) / peek.headWidth;
  const width = Math.round(peek.crop[2] * factor),
    height = Math.round(peek.crop[3] * factor),
    grip = peek.grip;
  const frame = {
    x: Math.round(
      clamp(
        full.x + (full.width - width) / 2,
        area.x,
        area.x + area.width - width,
      ),
    ),
    y: Math.round(
      clamp(
        full.y + (full.height - height) / 2,
        area.y,
        area.y + area.height - height,
      ),
    ),
    width,
    height,
  };
  if (edge === "left") frame.x = Math.round(area.x - width * (1 - grip));
  if (edge === "right")
    frame.x = Math.round(area.x + area.width - width * grip);
  if (edge === "top") frame.y = Math.round(area.y - height * grip);
  if (edge === "bottom")
    frame.y = Math.round(area.y + area.height - height * (1 - grip));
  return frame;
}
function facing(frame, area, previous) {
  const delta = frame.x + frame.width / 2 - area.x - area.width / 2;
  return Math.abs(delta) < 16 ? previous : delta > 0;
}
module.exports = { clamp, fullFrame, dock, peekFrame, facing };

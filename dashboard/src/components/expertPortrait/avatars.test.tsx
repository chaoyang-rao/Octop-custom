import * as React from "react";
import { readFileSync } from "node:fs";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SHAPES,
  COLORS,
  VIEWBOXES,
  avatarFrame,
  bubbleStyle,
  contrast,
  createExpertAvatars,
} from "./avatar-library.mjs";
import { createExpertPresentation, randomAvatar } from "./presentation.mjs";

const avatars = createExpertAvatars({ React });
const { TeamPortrait } = createExpertPresentation({ React, avatars });

function inside([x, y]: number[], polygon: number[][]) {
  let result = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i],
      [xj, yj] = polygon[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      result = !result;
  }
  return result;
}

describe("nine geometric portraits", () => {
  it("offers 81 saved combinations and their standalone assets", () => {
    expect(SHAPES).toHaveLength(9);
    expect(COLORS).toHaveLength(9);
    for (const shape of SHAPES) {
      for (const color of COLORS) {
        const url = avatars.avatarUrl(shape.id, color.id);
        expect(avatars.parseAvatarUrl(url)).toEqual({
          shape: shape.id,
          color: color.id,
        });
        const svg = readFileSync(`public${url}`, "utf8");
        expect(svg).toContain(`fill="${color.hex}"`);
        expect(svg).toContain('dur="6s"');
      }
    }
  });

  it("keeps every body and eye inside its frame throughout the loop", () => {
    for (const { id } of SHAPES) {
      const [x, y, width, height] = VIEWBOXES[id].split(" ").map(Number);
      expect(avatarFrame(id, "ink", 0)).toEqual(avatarFrame(id, "ink", 6));
      for (let sample = 0; sample < 150; sample++) {
        const frame = avatarFrame(id, "ink", sample / 25);
        for (const [px, py] of [...frame.body, ...frame.eyes.flat()]) {
          if (!(px > x && px < x + width && py > y && py < y + height))
            throw new Error(`${id}: clipped at sample ${sample}`);
        }
        for (const eye of frame.eyes.flat()) {
          if (!inside(eye, frame.body))
            throw new Error(`${id}: eye outside body at sample ${sample}`);
        }
        for (const [px, py] of frame.body) {
          if (
            !(
              px - 14 > x &&
              px + 14 < x + width &&
              py - 14 > y &&
              py + 14 < y + height
            )
          )
            throw new Error(
              `${id}: team separator clipped at sample ${sample}`,
            );
        }
        const mean = (points: number[][], axis: number) =>
          points.reduce((sum, point) => sum + point[axis], 0) / points.length;
        expect(mean(frame.eyes.flat(), 0)).toBeGreaterThan(mean(frame.body, 0));
        expect(mean(frame.eyes.flat(), 1)).toBeLessThan(mean(frame.body, 1));
      }
    }
  });

  it("keeps nine bubble colors readable without changing their base color", () => {
    for (const color of COLORS) {
      const style = bubbleStyle(color.id);
      expect(style.backgroundColor).toBe(color.hex);
      expect(
        contrast(style.backgroundColor, style.color),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("includes the new options in creation and preserves saved old IDs", () => {
    const picks = Array.from({ length: 4 }, () => randomAvatar(() => 0.9999));
    expect(
      picks.some((value) => value.shape === "capsule" && value.color === "red"),
    ).toBe(true);
    for (const id of [
      "blob",
      "pebble",
      "squircle",
      "droplet",
      "cloud",
      "star",
      "triangle",
    ])
      expect(
        avatars.parseAvatarUrl(`/expert-avatars/v2/${id}-jade.svg`),
      ).toEqual({
        shape: id,
        color: "jade",
      });
  });
});

describe("team portrait occupancy", () => {
  beforeEach(() => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
  });

  it.each([1, 2, 3, 4])(
    "fits %i equal-size members into a fixed slot",
    (count) => {
      const members = SHAPES.slice(0, count).map((shape, i) => ({
        agent_id: `member-${i}`,
        avatar_shape: shape.id,
        avatar_color: COLORS[i].id,
      }));
      const { container } = render(
        <TeamPortrait members={members} size={48} />,
      );
      const faces = [
        ...container.querySelectorAll<HTMLElement>(".octop-team-face"),
      ];
      expect(faces).toHaveLength(count);
      const side = Number.parseFloat(faces[0].style.width);
      for (const face of faces) {
        expect(Number.parseFloat(face.style.width)).toBe(side);
        expect(Number.parseFloat(face.style.height)).toBe(side);
        expect(Number.parseFloat(face.style.left)).toBeGreaterThanOrEqual(0);
        expect(Number.parseFloat(face.style.top)).toBeGreaterThanOrEqual(0);
        expect(Number.parseFloat(face.style.left) + side).toBeLessThanOrEqual(
          48.001,
        );
        expect(Number.parseFloat(face.style.top) + side).toBeLessThanOrEqual(
          48.001,
        );
      }
      expect(side).toBeGreaterThanOrEqual(count === 1 ? 48 : 48 * 0.64);
    },
  );
});

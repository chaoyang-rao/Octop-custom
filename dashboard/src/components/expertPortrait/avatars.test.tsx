import * as React from "react";
import { readFileSync } from "node:fs";
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SHAPES,
  COLORS,
  VIEWBOXES,
  avatarFrame,
  avatarPose,
  animatedSvg,
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

describe("geometric portraits", () => {
  it("offers the twelve exact colors and all 108 animated standalone assets", () => {
    expect(SHAPES).toHaveLength(9);
    expect(Object.fromEntries(COLORS.map(({ id, hex }) => [id, hex]))).toEqual({
      black: "#000000",
      brown: "#936439",
      red: "#FF263C",
      orange: "#FF6700",
      yellow: "#FF9800",
      lemon: "#FFD400",
      green: "#00C972",
      cyan: "#00BCA6",
      blue: "#1084FE",
      violet: "#9159FE",
      magenta: "#FF309B",
      gray: "#777777",
    });
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
        expect(svg).toBe(animatedSvg(shape.id, color.id));
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

  it("uses the approved oval eyes and keeps every live pose inside the avatar slot", () => {
    const { eyes } = avatarFrame("blob", "blue", 0);
    const extent = (points: number[][], axis: number) =>
      Math.max(...points.map((point) => point[axis])) -
      Math.min(...points.map((point) => point[axis]));
    for (const eye of eyes)
      expect(extent(eye, 1)).toBeGreaterThan(extent(eye, 0));
    expect(avatarPose("think", 1.32).gaze).toBeGreaterThan(0);
    expect(avatarPose("think", 3.12).gaze).toBeLessThan(0);
    expect(avatarPose("done", 2)).toEqual(avatarPose("idle", 0));
    for (const { id } of SHAPES) {
      const [left, top, width, height] = VIEWBOXES[id].split(" ").map(Number);
      for (const motion of ["think", "work", "wait", "done"] as const) {
        for (let tick = 0; tick <= 60; tick++) {
          const time = tick / 12;
          const frame = avatarFrame(id, "blue", time, avatarPose(motion, time));
          if (frame.eyes.flat().some((eye) => !inside(eye, frame.body))) {
            throw new Error(`${id}: ${motion} eye outside body at ${time}s`);
          }
          if (
            frame.body.some(
              ([x, y]) =>
                x < left + 13.99 ||
                x > left + width - 13.99 ||
                y < top + 13.99 ||
                y > top + height - 13.99,
            )
          )
            throw new Error(`${id}: ${motion} clipped at ${time}s`);
        }
      }
    }
  });

  it("keeps all twelve bubble colors readable without changing their base color", () => {
    for (const color of COLORS) {
      const style = bubbleStyle(color.id);
      expect(style.backgroundColor).toBe(color.hex);
      expect(
        contrast(style.backgroundColor, style.color),
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("renders existing colors using their replacement palette values", () => {
    const legacy = {
      ink: "#000000",
      cocoa: "#936439",
      coral: "#FF6700",
      amber: "#FF9800",
      jade: "#00BCA6",
      rose: "#FF309B",
      blue: "#1084FE",
      violet: "#9159FE",
      red: "#FF263C",
    };
    for (const [color, hex] of Object.entries(legacy)) {
      const url = avatars.avatarUrl("pebble", color);
      expect(avatarFrame("pebble", color, 0)).toMatchObject({
        shape: "pebble",
        base: hex,
      });
      expect(readFileSync(`public${url}`, "utf8")).toContain(`fill="${hex}"`);
    }
  });

  it("includes the new options in creation and preserves saved old IDs", () => {
    const picks = Array.from({ length: 4 }, () => randomAvatar(() => 0.9999));
    expect(
      picks.some(
        (value) => value.shape === "capsule" && value.color === "gray",
      ),
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

describe("avatar clock", () => {
  it("renders adjacent display frames and settles an idle portrait without a ticker", () => {
    const poseClock = createExpertAvatars({ React });
    const queue = new Map<number, FrameRequestCallback>();
    let next = 0;
    const raf = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((cb) => {
        queue.set(++next, cb);
        return next;
      });
    const cancel = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation((id) => {
        queue.delete(id);
      });
    const media = vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    const clock = vi.spyOn(performance, "now").mockReturnValue(1000);
    const { container, rerender, unmount } = render(
      <poseClock.Avatar motion="idle" />,
    );
    const shape = () =>
      container.querySelector("[data-avatar-body]")?.getAttribute("d");
    const draw = (ms: number) => {
      clock.mockReturnValue(ms);
      for (const [id, callback] of Array.from(queue)) {
        queue.delete(id);
        act(() => callback(ms));
      }
    };
    try {
      const neutral = shape();
      expect(queue.size).toBe(0);
      rerender(<poseClock.Avatar motion="work" />);
      draw(1300);
      const first = shape();
      draw(1316);
      const second = shape();
      draw(1332);
      expect(first).not.toBe(neutral);
      expect(second).not.toBe(first);
      expect(shape()).not.toBe(second);
      rerender(<poseClock.Avatar motion="idle" />);
      draw(1370);
      expect(shape()).not.toBe(neutral);
      draw(1590);
      expect(shape()).toBe(neutral);
      expect(queue.size).toBe(0);
    } finally {
      unmount();
      raf.mockRestore();
      cancel.mockRestore();
      media.mockRestore();
      clock.mockRestore();
    }
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

  it("marks only an explicitly identified primary, including renamed experts", () => {
    const primary = {
      agent_id: "main",
      name: "我的助手",
      is_team_primary: true,
      icon_url: "/expert-avatars/v2/pebble-jade.svg",
    };
    const { ExpertPortrait } = createExpertPresentation({
      React,
      avatars,
      useAgent: () => ({ agents: [primary], activeAgent: primary }),
    });
    const { container, rerender } = render(
      <ExpertPortrait agent={primary} size={48} />,
    );
    expect(container.querySelector(".octop-primary-badge")?.textContent).toBe(
      "主",
    );
    expect(container.querySelector(".octop-primary-face")).toHaveAttribute(
      "viewBox",
      VIEWBOXES.blob,
    );
    expect(
      container.querySelector(".octop-primary-face [data-avatar-body]"),
    ).toHaveAttribute("fill", "#000000");
    rerender(<ExpertPortrait iconUrl={primary.icon_url} size={48} />);
    expect(container.querySelector(".octop-primary-badge")).toBeNull();
    rerender(<ExpertPortrait agentId="main" size={36} />);
    expect(container.querySelector(".octop-primary-badge")?.textContent).toBe(
      "主",
    );
    rerender(<ExpertPortrait agent={{ ...primary, is_team_primary: false }} />);
    expect(container.querySelector(".octop-primary-badge")).toBeNull();
    rerender(
      <ExpertPortrait
        agent={{ ...primary, kind: "team", member_ids: ["main"] }}
      />,
    );
    expect(container.querySelector(".octop-primary-badge")).toBeNull();
  });

  it("keeps collages and the primary portrait scoped to their own conversations", () => {
    const primary = {
      agent_id: "primary",
      is_team_primary: true,
      work_status: "working",
    };
    const member = { agent_id: "member", work_status: "waiting" };
    const team = {
      kind: "team",
      primary_agent_id: "primary",
      member_ids: ["primary", "member"],
    };
    const { ExpertPortrait } = createExpertPresentation({
      React,
      avatars,
      useAgent: () => ({ agents: [primary, member] }),
    });
    const { container, rerender } = render(
      <>
        <ExpertPortrait
          agent={{ ...team, agent_id: "asked", work_status: "working" }}
        />
        <ExpertPortrait
          agent={{ ...team, agent_id: "idle", work_status: "idle" }}
        />
        <ExpertPortrait agent={primary} />
        <TeamPortrait members={[primary, member]} />
      </>,
    );
    const statuses = () =>
      Array.from(container.querySelectorAll("[data-avatar-motion]"), (avatar) =>
        avatar.getAttribute("data-avatar-motion"),
      );
    expect(statuses()).toEqual([
      "work",
      "idle",
      "idle",
      "idle",
      "idle",
      "idle",
      "idle",
    ]);
    rerender(
      <TeamPortrait
        members={[primary, member]}
        primaryId="primary"
        motion="wait"
      />,
    );
    expect(statuses()).toEqual(["wait", "idle"]);
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

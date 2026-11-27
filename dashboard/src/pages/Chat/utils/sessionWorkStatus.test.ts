import { describe, expect, it } from "vitest";
import { resolveSessionWorkStatus } from "./sessionWorkStatus";

describe("resolveSessionWorkStatus", () => {
  it("marks a live or server-active turn as working", () => {
    expect(resolveSessionWorkStatus({ id: "thr_1" }, new Set(["thr_1"]))).toBe(
      "working",
    );
    expect(
      resolveSessionWorkStatus({ id: "thr_1", turnActive: true }, new Set()),
    ).toBe("working");
  });

  it("shows a pending confirmation even while the outer turn remains active", () => {
    expect(
      resolveSessionWorkStatus(
        { id: "thr_1", turnActive: true, awaitingUser: true },
        new Set(),
      ),
    ).toBe("waiting");
    expect(
      resolveSessionWorkStatus(
        { id: "thr_1", awaitingUser: true },
        new Set(["thr_1"]),
      ),
    ).toBe("waiting");
  });

  it("marks a HITL pause as waiting", () => {
    expect(
      resolveSessionWorkStatus({ id: "thr_1", awaitingUser: true }, new Set()),
    ).toBe("waiting");
  });

  it("uses a completed reply only after active processing has ended", () => {
    expect(
      resolveSessionWorkStatus({ id: "thr_1", turnCompleted: true }, new Set()),
    ).toBe("complete");
    expect(
      resolveSessionWorkStatus(
        { id: "thr_1", turnCompleted: true },
        new Set(["thr_1"]),
      ),
    ).toBe("working");
  });

  it("leaves an idle session without a completion indicator", () => {
    expect(resolveSessionWorkStatus({ id: "thr_1" }, new Set())).toBe("idle");
  });
});

import { describe, expect, it } from "vitest";
import type { WorkflowStep } from "../../api/modules/tasks";
import { workflowGraphError } from "./workflowValidation";
const step = (key: string, depends_on: string[] = []): WorkflowStep => ({
  key,
  depends_on,
  title: key,
  agent_id: "owned",
  prompt: "Read inputs",
});
describe("editable workflow dependencies", () => {
  it("accepts reversed editing order with a valid dependency", () =>
    expect(workflowGraphError([step("b", ["a"]), step("a")])).toBeNull());
  it("explains duplicate keys", () =>
    expect(workflowGraphError([step("a"), step("a")])).toBe("duplicateStep"));
  it("detects a reference left by removing or renaming a step", () =>
    expect(workflowGraphError([step("b", ["a"])])).toBe("missingDependency"));
  it("detects cycles before saving", () =>
    expect(workflowGraphError([step("a", ["b"]), step("b", ["a"])])).toBe(
      "cyclicDependency",
    ));
});

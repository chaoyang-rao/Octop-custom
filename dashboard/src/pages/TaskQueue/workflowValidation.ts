import type { WorkflowStep } from "../../api/modules/tasks";

/** Check editable graph references before making a server request. */
export function workflowGraphError(
  steps: WorkflowStep[],
): "duplicateStep" | "missingDependency" | "cyclicDependency" | null {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  if (byKey.size !== steps.length) return "duplicateStep";
  if (steps.some((step) => step.depends_on.some((key) => !byKey.has(key))))
    return "missingDependency";
  const done = new Set<string>();
  while (done.size < byKey.size) {
    const ready = [...byKey.values()].filter(
      (step) =>
        !done.has(step.key) && step.depends_on.every((key) => done.has(key)),
    );
    if (!ready.length) return "cyclicDependency";
    ready.forEach((step) => done.add(step.key));
  }
  return null;
}

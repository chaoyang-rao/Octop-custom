import { Fragment, useEffect, useLayoutEffect, useRef } from "react";
import { CircleDot, Sparkles, Wand2 } from "../../../components/arcIcons";
import cx from "classnames";
import type { TrajectoryEvent } from "../../../api/modules/trajectory";
import { laneForKind, toLedgerRow } from "../utils/trajectoryModel";
import styles from "./TrajectoryLedger.module.less";

/** px from bottom — stay pinned to the live tail while the user is near it */
const FOLLOW_TAIL_THRESHOLD_PX = 80;

export interface TrajectoryLedgerProps {
  events: TrajectoryEvent[];
  selectedEventId: string | null;
  onSelect: (eventId: string) => void;
  /** Expand a folded assistant/turn summary row (DSH click-to-expand). */
  onExpandCollapsed?: (
    parentEventId: string,
    kind: "assistant" | "turn",
  ) => void;
  focusEventIds: ReadonlySet<string> | null;
  searchMatchIds: ReadonlySet<string> | null;
}

function distanceFromBottom(el: HTMLElement): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

function matchAttr(
  ids: ReadonlySet<string> | null,
  eventId: string,
): "true" | "false" | undefined {
  if (ids == null) return undefined;
  return ids.has(eventId) ? "true" : "false";
}

function KindIcon({ kind }: { kind: string }) {
  if (kind === "tool") {
    return <Wand2 className={styles.kindIcon} size={13} />;
  }
  if (kind === "assistant" || kind === "compacted") {
    return <Sparkles className={styles.kindIcon} size={13} />;
  }
  return <CircleDot className={styles.kindIcon} size={13} />;
}

function kindTagClass(kind: string): string {
  const lane = laneForKind(kind);
  if (lane === "tools") return styles.kindTool;
  if (lane === "model") return styles.kindAssistant;
  if (kind === "context") return styles.kindContext;
  if (kind === "system" || kind === "compacted") return styles.kindSystem;
  return styles.kindUser;
}

function ContentCell({
  kind,
  title,
  content,
  toolArgs,
  toolResult,
  toolCallOnly,
  collapsedSummary,
}: {
  kind: string;
  title: string;
  content: string;
  toolArgs: string | null;
  toolResult: string | null;
  toolCallOnly?: boolean;
  collapsedSummary?: boolean;
}) {
  if (collapsedSummary) {
    return (
      <span className={styles.collapsedSummary}>
        <span className={styles.collapsedEllipsis} aria-hidden>
          …
        </span>
        <span>{content || title}</span>
      </span>
    );
  }
  if (kind === "tool") {
    // List API often keeps only `name` in payload; summary already has
    // `name {args} → result` (DSH-style). Prefer structured fields when present.
    if (!toolArgs && !toolResult) {
      return (
        <span className={styles.toolLine}>
          <span className={styles.toolResult}>{content || title}</span>
        </span>
      );
    }
    return (
      <span className={styles.toolLine}>
        <span className={styles.toolName}>{title}</span>
        {toolArgs ? <span className={styles.toolArgs}>{toolArgs}</span> : null}
        {toolResult ? (
          <>
            <span className={styles.arrow} aria-hidden>
              →
            </span>
            <span className={styles.toolResult}>{toolResult}</span>
          </>
        ) : null}
      </span>
    );
  }
  if (toolCallOnly) {
    return (
      <span className={styles.contentText}>
        <span className={styles.toolCallOnlyLabel}>{title}</span>
        {content && content !== title ? (
          <span className={styles.collapsedCalls}>{content}</span>
        ) : null}
      </span>
    );
  }
  return <span className={styles.contentText}>{content || title}</span>;
}

export default function TrajectoryLedger({
  events,
  selectedEventId,
  onSelect,
  onExpandCollapsed,
  focusEventIds,
  searchMatchIds,
}: TrajectoryLedgerProps) {
  const paneRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const followTailRef = useRef(true);
  const lastEventId = events[events.length - 1]?.event_id ?? null;
  const turnNumbers = new Map<string, number>();
  for (const event of events) {
    if (event.turn_id == null || turnNumbers.has(event.turn_id)) continue;
    turnNumbers.set(event.turn_id, turnNumbers.size + 1);
  }

  useEffect(() => {
    const pane = paneRef.current;
    if (pane == null) return;
    const onScroll = () => {
      followTailRef.current =
        distanceFromBottom(pane) <= FOLLOW_TAIL_THRESHOLD_PX;
    };
    pane.addEventListener("scroll", onScroll, { passive: true });
    return () => pane.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    if (!followTailRef.current || lastEventId == null) return;
    const pane = paneRef.current;
    if (pane == null) return;
    pane.scrollTop = pane.scrollHeight;
  }, [events.length, lastEventId]);

  useEffect(() => {
    if (selectedEventId == null) return;
    const node = rowRefs.current.get(selectedEventId);
    if (typeof node?.scrollIntoView !== "function") return;
    node.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [selectedEventId]);

  return (
    <div
      ref={paneRef}
      className={styles.tablePane}
      data-testid="trajectory-ledger-pane"
    >
      <table className={styles.table}>
        <tbody>
          {events.map((event, index) => {
            const row = toLedgerRow(event);
            const selected = selectedEventId === row.id;
            const prevTurn = events[index - 1]?.turn_id;
            const turnStart =
              event.turn_id != null && event.turn_id !== prevTurn;
            const turnNumber =
              event.turn_id != null
                ? turnNumbers.get(event.turn_id)
                : undefined;
            const turnLabel =
              turnNumber != null ? `T${turnNumber}` : event.turn_id;
            const showRequest =
              row.kind === "assistant" &&
              row.requestSeq != null &&
              !row.collapsedSummary;
            const accessibleName = row.collapsedSummary
              ? row.content || row.title
              : [
                  showRequest ? `Request #${row.requestSeq}` : null,
                  row.kindLabel,
                  row.kind === "tool"
                    ? [row.title, row.toolArgs, row.toolResult, row.content]
                        .filter(Boolean)
                        .filter(
                          (part, partIndex, all) =>
                            all.indexOf(part) === partIndex,
                        )
                        .join(" ")
                    : row.toolCallOnly
                    ? [row.title, row.content]
                        .filter(Boolean)
                        .filter(
                          (part, partIndex, all) =>
                            all.indexOf(part) === partIndex,
                        )
                        .join(" ")
                    : row.content || row.title,
                ]
                  .filter(Boolean)
                  .join(", ");

            const activate = () => {
              if (
                row.collapsedSummary &&
                row.collapsedParentId &&
                onExpandCollapsed
              ) {
                onExpandCollapsed(
                  row.collapsedParentId,
                  row.collapsedSummaryKind ?? "assistant",
                );
                return;
              }
              onSelect(row.id);
            };

            return (
              <Fragment key={row.id}>
                <tr
                  ref={(node) => {
                    if (node) rowRefs.current.set(row.id, node);
                    else rowRefs.current.delete(row.id);
                  }}
                  className={cx(
                    styles.row,
                    selected && styles.rowSelected,
                    row.isError && styles.rowError,
                    row.collapsedSummary && styles.rowCollapsedSummary,
                  )}
                  data-kind={
                    row.collapsedSummary ? "collapsed-summary" : row.kind
                  }
                  data-turn-start={
                    turnStart && !row.collapsedSummary ? "true" : undefined
                  }
                  data-selected={selected ? "true" : "false"}
                  data-focus-match={matchAttr(focusEventIds, row.id)}
                  data-search-match={matchAttr(searchMatchIds, row.id)}
                  tabIndex={0}
                  role="button"
                  aria-selected={selected}
                  aria-label={accessibleName}
                  onClick={activate}
                  onKeyDown={(keyboardEvent) => {
                    if (
                      keyboardEvent.key === "Enter" ||
                      keyboardEvent.key === " "
                    ) {
                      keyboardEvent.preventDefault();
                      activate();
                    }
                  }}
                >
                  <td className={styles.event}>
                    <span className={styles.turnRail} aria-hidden />
                    {selected && !row.collapsedSummary ? (
                      <span className={styles.selectionRail} aria-hidden />
                    ) : null}
                    {turnStart && turnLabel && !row.collapsedSummary ? (
                      <span
                        className={styles.turnLabel}
                        data-testid="trajectory-turn-header"
                        title={event.turn_id ?? turnLabel}
                      >
                        {turnLabel}
                      </span>
                    ) : null}
                    {!row.collapsedSummary ? (
                      <span className={styles.eventInner}>
                        {showRequest ? (
                          <span className={styles.requestLabel}>
                            {`Request #${row.requestSeq}`}
                          </span>
                        ) : null}
                        <span
                          className={cx(styles.kindTag, kindTagClass(row.kind))}
                          title={row.kindLabel}
                        >
                          <KindIcon kind={row.kind} />
                          <span className={styles.kindTagLabel}>
                            {row.kindLabel}
                          </span>
                        </span>
                      </span>
                    ) : null}
                  </td>
                  <td className={styles.content}>
                    <ContentCell
                      kind={row.kind}
                      title={row.title}
                      content={row.content}
                      toolArgs={row.toolArgs}
                      toolResult={row.toolResult}
                      toolCallOnly={row.toolCallOnly}
                      collapsedSummary={row.collapsedSummary}
                    />
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Popover, Spin, Drawer } from "antd";
import {
  octopThreadsApi,
  type ContextUsageBreakdown,
  type ContextUsageSegmentKey,
} from "../../../api/modules/octopThreads";
import { isPendingThread } from "../hooks/useSessions";
import { contextUsedPercent } from "../hooks/useChatContextWindow";
import styles from "../index.module.less";

const BREAKDOWN_CACHE_TTL_MS = 30_000;

const SEGMENT_COLORS: Record<ContextUsageSegmentKey, string> = {
  system_prompt: "#9ca3af",
  tool_definitions: "#c4b5fd",
  rules: "#86efac",
  skills: "#fbbf24",
  mcp: "#e879f9",
  subagent_definitions: "#3b82f6",
  conversation: "#22d3ee",
};

const DECISION_SAVED_COLOR = "#fb923c";

function formatTokenK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return String(n);
}

interface ContextWindowRingProps {
  usedTokens: number | null;
  /** No provider usage_metadata — ring/breakdown are local estimates. */
  usageEstimated?: boolean;
  maxTokens: number;
  agentId?: string | null;
  threadId?: string | null;
  selectedConnectors?: string[];
  isMobile?: boolean;
  /** Session total omitted by the decision filter. Same figure as 本会话累计. */
  decisionSaved?: number;
  isStreaming?: boolean;
}

export default function ContextWindowRing({
  usedTokens,
  usageEstimated = false,
  maxTokens,
  agentId,
  threadId,
  selectedConnectors = [],
  isMobile = false,
  decisionSaved = 0,
  isStreaming = false,
}: ContextWindowRingProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [breakdown, setBreakdown] = useState<ContextUsageBreakdown | null>(
    null,
  );
  const cacheRef = useRef<{
    key: string;
    at: number;
    data: ContextUsageBreakdown;
  } | null>(null);
  const requestIdRef = useRef(0);
  // Stream hint — kept in a ref so prefetch does not re-fire on every token tick.
  const hintUsedRef = useRef(usedTokens ?? 0);
  hintUsedRef.current = usedTokens ?? 0;

  const max = Math.max(0, maxTokens);
  const hintUsed = usedTokens ?? 0;
  const connectorKey = JSON.stringify(selectedConnectors);

  const cacheKey = useMemo(
    () => [agentId ?? "", threadId ?? "", String(max), connectorKey].join("|"),
    [agentId, threadId, max, connectorKey],
  );

  const loadBreakdown = useCallback(
    async (opts?: { silent?: boolean; force?: boolean }) => {
      if (!agentId || !threadId || isPendingThread(threadId)) return;
      const requestId = ++requestIdRef.current;
      const cached = cacheRef.current;
      const hint = hintUsedRef.current;
      // A new model call moves the live total. The 30s cache would otherwise
      // keep the previous request's decision savings on screen.
      const hintMoved =
        hint > 0 &&
        (cached?.data.used_tokens ?? 0) > 0 &&
        Math.abs(hint - (cached?.data.used_tokens ?? 0)) >= 64;
      if (
        !opts?.force &&
        !hintMoved &&
        cached &&
        cached.key === cacheKey &&
        Date.now() - cached.at < BREAKDOWN_CACHE_TTL_MS
      ) {
        setBreakdown(cached.data);
        return;
      }
      if (!opts?.silent) setLoading(true);
      try {
        // Prefer a pure harness snapshot. Pass stream hint only as a fallback
        // when we do not already have a segmented breakdown cached.
        const haveSegments =
          cached?.key === cacheKey &&
          (cached.data.segments?.length ?? 0) > 0 &&
          cached.data.used_tokens > 0;
        const data = await octopThreadsApi.contextUsage(agentId, threadId, {
          maxTokens: max,
          inputTokens: !haveSegments && hint > 0 ? hint : undefined,
          mcpServers: JSON.parse(connectorKey) as string[],
        });
        if (requestId !== requestIdRef.current) return;
        cacheRef.current = { key: cacheKey, at: Date.now(), data };
        setBreakdown(data);
      } catch {
        if (requestId === requestIdRef.current && !opts?.silent)
          setBreakdown(null);
      } finally {
        if (requestId === requestIdRef.current && !opts?.silent)
          setLoading(false);
      }
    },
    [agentId, threadId, max, connectorKey, cacheKey],
  );

  // Reset detail cache on thread/filter changes. The ring itself keeps growing
  // from the live/persisted token hint and never needs a checkpoint read.
  useEffect(() => {
    setBreakdown(null);
    cacheRef.current = null;
  }, [cacheKey]);

  useEffect(() => {
    void loadBreakdown({ silent: true, force: true });
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadBreakdown, usedTokens, isStreaming]);

  const ringMax = breakdown ? breakdown.max_tokens : max;
  const capacityKnown = ringMax > 0;
  const ringUsed = useMemo(() => {
    if (breakdown) {
      return ringMax > 0
        ? Math.min(breakdown.used_tokens, ringMax)
        : breakdown.used_tokens;
    }
    if (hintUsed > 0)
      return ringMax > 0 ? Math.min(hintUsed, ringMax) : hintUsed;
    // Until prefetch returns, show last-call hint (capped so a stale
    // turn-sum cannot flash a full ring).
    return 0;
  }, [breakdown, hintUsed, ringMax]);

  const { usedPct, strokeColor, dashOffset, circumference } = useMemo(() => {
    const usedRatio = ringMax > 0 ? Math.min(ringUsed / ringMax, 1) : 0;
    const usedPercent = contextUsedPercent(ringUsed, ringMax);
    const r = 13;
    const circ = 2 * Math.PI * r;
    let color =
      ringMax > 0
        ? "var(--fn-color-success, #22c55e)"
        : "var(--fn-color-text-tertiary, #9ca3af)";
    if (usedRatio >= 0.8) {
      color = "var(--fn-color-danger, #ef4444)";
    } else if (usedRatio >= 0.5) {
      color = "var(--fn-color-warning, #eab308)";
    }
    return {
      usedPct: usedPercent,
      strokeColor: color,
      dashOffset: circ * (1 - usedRatio),
      circumference: circ,
    };
  }, [ringUsed, ringMax]);

  const isEstimate = breakdown?.estimated ?? usageEstimated;
  const tooltip = t(
    capacityKnown
      ? isEstimate
        ? "chat.contextWindow.estimatedTooltip"
        : "chat.contextWindow.tooltip"
      : "chat.contextWindow.capacityUnknownTooltip",
    {
      used: formatTokenK(ringUsed),
      max: formatTokenK(ringMax),
      percent: usedPct,
    },
  );

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      void loadBreakdown();
    }
  };

  const display = breakdown ?? {
    max_tokens: ringMax,
    used_tokens: ringUsed,
    segments: [] as ContextUsageBreakdown["segments"],
  };
  const displayUsed = display.used_tokens > 0 ? display.used_tokens : ringUsed;
  const displayMax = display.max_tokens;
  const displayPct = contextUsedPercent(displayUsed, displayMax);
  const segments =
    display.segments.length > 0
      ? display.segments
      : displayUsed > 0
      ? ([
          { key: "conversation", tokens: displayUsed },
        ] as ContextUsageBreakdown["segments"])
      : display.segments;
  const segmentTotal = segments.reduce((sum, item) => sum + item.tokens, 0);
  // The legend row matches 本会话累计. The snapshot field is only the latest
  // model call, which is much smaller once a turn has called the model again.
  const savedTokens =
    decisionSaved > 0 ? decisionSaved : breakdown?.decision_saved ?? 0;

  const popoverContent = (
    <div className={styles.contextUsagePanel}>
      <div className={styles.contextUsageTitle}>
        {t("chat.contextWindow.breakdownTitle")}
      </div>
      <div className={styles.contextUsageSubtitle}>
        {capacityKnown
          ? t("chat.contextWindow.breakdownPercent", { percent: displayPct })
          : t("chat.contextWindow.capacityUnknown")}
      </div>
      <div className={styles.contextUsageHint}>
        {isEstimate
          ? t("chat.contextWindow.estimateHint")
          : t("chat.contextWindow.breakdownHint")}
      </div>
      {loading ? (
        <div className={styles.contextUsageLoading}>
          <Spin size="small" />
        </div>
      ) : (
        <>
          {capacityKnown ? (
            <div
              className={styles.contextUsageBar}
              role="img"
              aria-label={t("chat.contextWindow.breakdownTitle")}
            >
              {segmentTotal > 0 ? (
                segments.map((segment) => (
                  <span
                    key={segment.key}
                    className={styles.contextUsageBarSegment}
                    style={{
                      // Provider input usage owns the total bar width. Segment
                      // estimates contribute only their relative composition.
                      flexGrow: (displayUsed * segment.tokens) / segmentTotal,
                      background: SEGMENT_COLORS[segment.key],
                    }}
                  />
                ))
              ) : (
                <span
                  className={styles.contextUsageBarSegment}
                  style={{
                    flexGrow: displayUsed,
                    background: strokeColor,
                  }}
                />
              )}
              <span
                className={styles.contextUsageBarRemainder}
                style={{ flexGrow: Math.max(displayMax - displayUsed, 0) }}
              />
            </div>
          ) : null}
          <ul className={styles.contextUsageLegend}>
            {segments.map((segment) => (
              <li key={segment.key} className={styles.contextUsageLegendItem}>
                <span
                  className={styles.contextUsageLegendSwatch}
                  style={{ background: SEGMENT_COLORS[segment.key] }}
                />
                <span className={styles.contextUsageLegendLabel}>
                  {t(`chat.contextWindow.segments.${segment.key}`)}
                </span>
                <span className={styles.contextUsageLegendValue}>
                  ~{formatTokenK(segment.tokens)}
                </span>
              </li>
            ))}
            {segments.length === 0 && (
              <li className={styles.contextUsageLegendItem}>
                <span className={styles.contextUsageLegendLabel}>
                  {tooltip}
                </span>
              </li>
            )}
            {savedTokens > 0 ? (
              <li className={styles.contextUsageLegendItem}>
                <span
                  className={styles.contextUsageLegendSwatch}
                  style={{ background: DECISION_SAVED_COLOR }}
                />
                <span className={styles.contextUsageLegendLabel}>
                  {t("chat.contextWindow.decisionSaved")}
                </span>
                <span className={styles.contextUsageLegendValue}>
                  ~{formatTokenK(savedTokens)}
                </span>
              </li>
            ) : null}
          </ul>
        </>
      )}
    </div>
  );

  const ringInner = (
    <>
      <svg className={styles.contextRingSvg} viewBox="0 0 32 32" aria-hidden>
        <circle
          className={styles.contextRingTrack}
          cx="16"
          cy="16"
          r="13"
          fill="none"
          strokeWidth="3"
        />
        <circle
          className={styles.contextRingProgress}
          cx="16"
          cy="16"
          r="13"
          fill="none"
          strokeWidth="3"
          stroke={strokeColor}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform="rotate(-90 16 16)"
        />
      </svg>
      <span className={styles.contextRingLabel}>
        {capacityKnown ? usedPct : "?"}
      </span>
    </>
  );

  const ring = (
    <div
      className={styles.contextRingBtn}
      role="progressbar"
      aria-valuenow={capacityKnown ? usedPct : undefined}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={tooltip}
    >
      {ringInner}
    </div>
  );

  if (!agentId || !threadId) {
    return ring;
  }

  if (isMobile) {
    return (
      <>
        <button
          type="button"
          className={styles.contextRingBtn}
          onClick={() => handleOpenChange(true)}
          aria-label={tooltip}
        >
          {ringInner}
        </button>
        <Drawer
          open={open}
          onClose={() => handleOpenChange(false)}
          placement="bottom"
          height="auto"
          title={t("chat.contextWindow.breakdownTitle")}
          className={styles.mobilePickerDrawer}
          styles={{
            body: {
              padding: "12px 16px calc(16px + env(safe-area-inset-bottom))",
            },
          }}
          destroyOnHidden
        >
          {popoverContent}
        </Drawer>
      </>
    );
  }

  return (
    <Popover
      content={popoverContent}
      trigger="click"
      open={open}
      onOpenChange={handleOpenChange}
      placement="topRight"
      overlayClassName={styles.contextUsagePopover}
    >
      {ring}
    </Popover>
  );
}

import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";
import type { Message } from "./core";

/** The companion owns its scroll behavior so it can build without the dashboard. */
export function useChatScroll(
  scrollerRef: RefObject<HTMLDivElement>,
  messages: Message[],
  sessionKey: string,
  visible: boolean,
) {
  const spacerRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<{ sessionKey: string; messageId: string } | null>(
    null,
  );
  const previousSessionRef = useRef(sessionKey);
  const followingRef = useRef(true);
  const previousTopRef = useRef(0);

  const prepareSend = useCallback(
    (messageId: string) => {
      anchorRef.current = { sessionKey, messageId };
      followingRef.current = true;
    },
    [sessionKey],
  );

  const update = useCallback(() => {
    const scroller = scrollerRef.current;
    const spacer = spacerRef.current;
    if (!scroller || !spacer) return;
    const turn = anchorRef.current;
    // History can replace optimistic IDs; the current turn remains the last
    // user message in this room after that reconciliation.
    const anchor =
      turn?.sessionKey === sessionKey
        ? Array.from(
            scroller.querySelectorAll<HTMLElement>("[data-message-id]"),
          ).find((element) => element.dataset.messageId === turn.messageId) ??
          Array.from(
            scroller.querySelectorAll<HTMLElement>(".message.user"),
          ).at(-1)
        : null;
    const padding = getComputedStyle(scroller);
    const turnHeight = anchor
      ? spacer.getBoundingClientRect().top - anchor.getBoundingClientRect().top
      : scroller.clientHeight;
    const height = Math.max(
      0,
      Math.floor(
        scroller.clientHeight -
          parseFloat(padding.paddingTop || "0") -
          parseFloat(padding.paddingBottom || "0") -
          turnHeight,
      ),
    );
    if (spacer.style.height !== `${height}px`)
      spacer.style.height = `${height}px`;
    if (followingRef.current) {
      scroller.scrollTop = scroller.scrollHeight;
    }
    previousTopRef.current = scroller.scrollTop;
  }, [scrollerRef, sessionKey]);

  useLayoutEffect(() => {
    if (previousSessionRef.current !== sessionKey) {
      previousSessionRef.current = sessionKey;
      followingRef.current = true;
    }
    update();
  }, [messages, sessionKey, visible, update]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!visible || !scroller) return;
    const onScroll = () => {
      const gap =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      if (scroller.scrollTop < previousTopRef.current - 1 && gap > 12) {
        followingRef.current = false;
      } else if (gap <= 12) {
        followingRef.current = true;
      }
      previousTopRef.current = scroller.scrollTop;
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) followingRef.current = false;
    };
    let touchY = 0;
    const onTouchStart = (event: TouchEvent) => {
      touchY = event.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (event: TouchEvent) => {
      if ((event.touches[0]?.clientY ?? 0) - touchY > 10) {
        followingRef.current = false;
      }
    };
    const resize = new ResizeObserver(update);
    const observeChildren = () => {
      for (const child of Array.from(scroller.children)) resize.observe(child);
    };
    resize.observe(scroller);
    observeChildren();
    const mutation = new MutationObserver(observeChildren);
    mutation.observe(scroller, { childList: true });
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("touchstart", onTouchStart, { passive: true });
    scroller.addEventListener("touchmove", onTouchMove, { passive: true });
    return () => {
      resize.disconnect();
      mutation.disconnect();
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("touchstart", onTouchStart);
      scroller.removeEventListener("touchmove", onTouchMove);
    };
  }, [scrollerRef, sessionKey, visible, update]);

  return { spacerRef, prepareSend };
}

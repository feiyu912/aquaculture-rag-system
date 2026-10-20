"use client";

import * as React from "react";

const STORAGE_KEY = "aqua-rag:context-width";

export const CONTEXT_MIN = 224;
export const CONTEXT_MAX = 520;
export const CONTEXT_DEFAULT = 288;

/**
 * Persisted width of the context panel.
 *
 * The panel is a fixed-width column by default, which is wrong on narrow
 * windows where it eats the conversation area. Dragging the divider lets the
 * user trade the two off.
 */
export function useContextWidth() {
  const [width, setWidth] = React.useState(CONTEXT_DEFAULT);

  React.useEffect(() => {
    const stored = Number.parseInt(window.localStorage.getItem(STORAGE_KEY) ?? "", 10);
    if (Number.isFinite(stored) && stored >= CONTEXT_MIN && stored <= CONTEXT_MAX) {
      setWidth(stored);
    }
  }, []);

  const update = React.useCallback((next: number) => {
    const clamped = Math.min(CONTEXT_MAX, Math.max(CONTEXT_MIN, Math.round(next)));
    setWidth(clamped);
    window.localStorage.setItem(STORAGE_KEY, String(clamped));
  }, []);

  const reset = React.useCallback(() => {
    setWidth(CONTEXT_DEFAULT);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { width, setWidth: update, reset };
}

/**
 * Pointer-driven resize handle for the context panel.
 *
 * Uses pointer capture so the drag keeps tracking even when the pointer
 * leaves the handle, and supports keyboard resizing for accessibility.
 */
export function useResizeHandle({
  onResize,
  onReset,
  currentWidth,
}: {
  onResize: (width: number) => void;
  onReset: () => void;
  currentWidth: number;
}) {
  const [dragging, setDragging] = React.useState(false);
  const originRef = React.useRef({ x: 0, width: 0 });
  const panelRef = React.useRef<HTMLElement | null>(null);

  const onPointerDown = React.useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const panel = panelRef.current;
    if (!panel) return;
    event.preventDefault();
    originRef.current = {
      x: event.clientX,
      width: panel.getBoundingClientRect().width,
    };
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }, []);

  const onPointerMove = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      const delta = event.clientX - originRef.current.x;
      onResize(originRef.current.width + delta);
    },
    [dragging, onResize],
  );

  const endDrag = React.useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, [dragging]);

  const onKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 48 : 16;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        onResize(currentWidth - step);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        onResize(currentWidth + step);
      } else if (event.key === "Home") {
        event.preventDefault();
        onResize(CONTEXT_MIN);
      } else if (event.key === "End") {
        event.preventDefault();
        onResize(CONTEXT_MAX);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onReset();
      }
    },
    [currentWidth, onResize, onReset],
  );

  return {
    dragging,
    panelRef,
    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onKeyDown,
      onDoubleClick: onReset,
    },
  };
}

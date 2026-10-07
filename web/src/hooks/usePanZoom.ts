import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export interface View {
  x: number;
  y: number;
  scale: number;
}

// Low enough for a wide map to fit a phone screen
export const MIN_SCALE = 0.03;
export const MAX_SCALE = 4;
const BUTTON_STEP = 1.3;
const WHEEL_SENSITIVITY = 0.0015;
// Pointer travel (px) before a press counts as a drag rather than a click
const DRAG_THRESHOLD = 4;

function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/** Scale the view by `factor`, keeping the content under the point (px, py) in place. */
export function zoomAround(view: View, factor: number, px: number, py: number): View {
  const scale = clampScale(view.scale * factor);
  const applied = scale / view.scale;
  return {
    scale,
    x: px - (px - view.x) * applied,
    y: py - (py - view.y) * applied,
  };
}

/** The view that shows all of the content, centred, without enlarging it past 100%. */
export function fitView(
  content: { width: number; height: number },
  viewport: { width: number; height: number },
  margin = 16,
): View {
  if (!content.width || !content.height || !viewport.width || !viewport.height) {
    return { x: 0, y: 0, scale: 1 };
  }
  const scale = clampScale(
    Math.min(
      (viewport.width - margin * 2) / content.width,
      (viewport.height - margin * 2) / content.height,
      1,
    ),
  );
  return {
    scale,
    x: (viewport.width - content.width * scale) / 2,
    y: (viewport.height - content.height * scale) / 2,
  };
}

export interface PanZoom {
  /** Current zoom, for display (1 = 100%) */
  scale: number;
  zoomIn: () => void;
  zoomOut: () => void;
  /** Show the whole content, centred */
  fit: () => void;
}

/**
 * Visual pan and zoom for an SVG rendered inside `contentRef`, within `viewportRef`.
 * Drag to move, wheel or pinch to zoom. A drag does not count as a click on the content.
 * The view is refitted whenever `contentKey` changes (a new SVG was rendered).
 */
export function usePanZoom(
  viewportRef: RefObject<HTMLElement>,
  contentRef: RefObject<HTMLElement>,
  contentKey: unknown,
): PanZoom {
  const viewRef = useRef<View>({ x: 0, y: 0, scale: 1 });
  const [scale, setScale] = useState(1);

  const apply = useCallback(
    (view: View) => {
      viewRef.current = view;
      const content = contentRef.current;
      if (content) {
        content.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
      }
      setScale(view.scale);
    },
    [contentRef],
  );

  const fit = useCallback(() => {
    const viewport = viewportRef.current;
    const svg = contentRef.current?.querySelector("svg");
    if (!viewport || !svg) return;
    // Give the SVG its natural size; mermaid otherwise stretches it to the container
    const box = svg.viewBox?.baseVal;
    const width = box?.width || svg.getBoundingClientRect().width;
    const height = box?.height || svg.getBoundingClientRect().height;
    svg.style.maxWidth = "none";
    svg.style.width = `${width}px`;
    svg.style.height = `${height}px`;
    apply(fitView({ width, height }, { width: viewport.clientWidth, height: viewport.clientHeight }));
  }, [viewportRef, contentRef, apply]);

  const zoomBy = useCallback(
    (factor: number) => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      apply(zoomAround(viewRef.current, factor, viewport.clientWidth / 2, viewport.clientHeight / 2));
    },
    [viewportRef, apply],
  );

  // Refit when a new SVG is rendered (after React has put it in the DOM)
  useEffect(() => {
    const frame = requestAnimationFrame(fit);
    return () => cancelAnimationFrame(frame);
  }, [contentKey, fit]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const pointers = new Map<number, { x: number; y: number }>();
    let dragged = false;
    let travelled = 0;

    const local = (event: { clientX: number; clientY: number }) => {
      const rect = viewport.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const point = local(event);
      apply(zoomAround(viewRef.current, Math.exp(-event.deltaY * WHEEL_SENSITIVITY), point.x, point.y));
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      pointers.set(event.pointerId, local(event));
      if (pointers.size === 1) {
        dragged = false;
        travelled = 0;
      }
    };

    const onPointerMove = (event: PointerEvent) => {
      const previous = pointers.get(event.pointerId);
      if (!previous) return;
      const current = local(event);
      const view = viewRef.current;

      if (pointers.size === 1) {
        travelled += Math.hypot(current.x - previous.x, current.y - previous.y);
        if (!dragged && travelled > DRAG_THRESHOLD) {
          dragged = true;
          // Capture only once it is a drag, so a plain click still reaches the node
          viewport.setPointerCapture(event.pointerId);
          viewport.style.cursor = "grabbing";
        }
        if (dragged) {
          apply({ ...view, x: view.x + current.x - previous.x, y: view.y + current.y - previous.y });
        }
      } else if (pointers.size === 2) {
        // Pinch: zoom around the midpoint of the two fingers, and follow it
        dragged = true;
        const other = [...pointers.entries()].find(([id]) => id !== event.pointerId)?.[1];
        if (other) {
          const before = Math.hypot(previous.x - other.x, previous.y - other.y);
          const after = Math.hypot(current.x - other.x, current.y - other.y);
          const midBefore = { x: (previous.x + other.x) / 2, y: (previous.y + other.y) / 2 };
          const midAfter = { x: (current.x + other.x) / 2, y: (current.y + other.y) / 2 };
          const zoomed = zoomAround(view, before > 0 ? after / before : 1, midBefore.x, midBefore.y);
          apply({
            ...zoomed,
            x: zoomed.x + midAfter.x - midBefore.x,
            y: zoomed.y + midAfter.y - midBefore.y,
          });
        }
      }
      pointers.set(event.pointerId, current);
    };

    const onPointerEnd = (event: PointerEvent) => {
      pointers.delete(event.pointerId);
      if (pointers.size === 0) viewport.style.cursor = "";
    };

    // A drag or pinch must not also act as a click on the node under the pointer
    const onClickCapture = (event: MouseEvent) => {
      if (dragged) {
        event.stopPropagation();
        event.preventDefault();
        dragged = false;
      }
    };

    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("pointerdown", onPointerDown);
    viewport.addEventListener("pointermove", onPointerMove);
    viewport.addEventListener("pointerup", onPointerEnd);
    viewport.addEventListener("pointercancel", onPointerEnd);
    viewport.addEventListener("click", onClickCapture, true);
    return () => {
      viewport.removeEventListener("wheel", onWheel);
      viewport.removeEventListener("pointerdown", onPointerDown);
      viewport.removeEventListener("pointermove", onPointerMove);
      viewport.removeEventListener("pointerup", onPointerEnd);
      viewport.removeEventListener("pointercancel", onPointerEnd);
      viewport.removeEventListener("click", onClickCapture, true);
    };
    // contentKey: the viewport element is mounted only once there is a graph
  }, [viewportRef, apply, contentKey]);

  return {
    scale,
    zoomIn: () => zoomBy(BUTTON_STEP),
    zoomOut: () => zoomBy(1 / BUTTON_STEP),
    fit,
  };
}

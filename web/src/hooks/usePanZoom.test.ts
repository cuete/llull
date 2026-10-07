import { describe, expect, it } from "vitest";
import { MAX_SCALE, MIN_SCALE, fitView, zoomAround } from "./usePanZoom";

describe("zoomAround", () => {
  it("keeps the content under the pointer in place", () => {
    const view = { x: 40, y: -20, scale: 1 };
    const pointer = { x: 300, y: 200 };
    // The content point under the pointer before zooming
    const contentX = (pointer.x - view.x) / view.scale;
    const contentY = (pointer.y - view.y) / view.scale;

    const zoomed = zoomAround(view, 2, pointer.x, pointer.y);

    expect(zoomed.scale).toBe(2);
    expect(zoomed.x + contentX * zoomed.scale).toBeCloseTo(pointer.x);
    expect(zoomed.y + contentY * zoomed.scale).toBeCloseTo(pointer.y);
  });

  it("stops at the zoom limits", () => {
    const view = { x: 0, y: 0, scale: 1 };
    expect(zoomAround(view, 1000, 0, 0).scale).toBe(MAX_SCALE);
    expect(zoomAround(view, 0.0001, 0, 0).scale).toBe(MIN_SCALE);
  });
});

describe("fitView", () => {
  it("shrinks a large map to fit and centres it", () => {
    const view = fitView({ width: 4000, height: 1000 }, { width: 1000, height: 600 }, 0);
    expect(view.scale).toBeCloseTo(0.25);
    expect(view.x).toBeCloseTo(0);
    expect(view.y).toBeCloseTo((600 - 1000 * 0.25) / 2);
  });

  it("does not enlarge a small map past 100%", () => {
    const view = fitView({ width: 200, height: 100 }, { width: 1000, height: 600 });
    expect(view.scale).toBe(1);
    expect(view.x).toBe(400);
    expect(view.y).toBe(250);
  });
});

import { describe, expect, it } from "vitest";

import { allNavigationPaths } from "../lib/navigation";

describe("navigation", () => {
  it("contains every top-level product route", () => {
    expect(allNavigationPaths).toEqual([
      "/competition",
      "/dashboard",
      "/patients",
      "/health-records",
      "/imaging",
      "/trends",
      "/risk-analysis",
      "/recommendations",
      "/ai-report",
      "/ai-chat",
      "/admin/exam-items",
      "/admin/medical-rules",
      "/admin/models",
      "/demo",
    ]);
  });
});

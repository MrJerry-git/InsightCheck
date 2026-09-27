import { describe, expect, it } from "vitest";
import { coverage, recommendations } from "../components/competition/domain";
import type { Report } from "../components/prevention/types";

const report = {
  input: { visits: [{ sbp: 120, total_c: 5, hdl_c: 1.3, bmi: null, egfr: null, hba1c: null, fasting_glucose: null }] },
  recommendations: [
    { code: "bp", title: "血压" }, { code: "glucose", title: "血糖" },
    { code: "kidney", title: "肾功能" }, { code: "lipids", title: "血脂" }, { code: "bp", title: "重复血压" },
  ],
} as unknown as Report;

describe("competition system routing", () => {
  it("does not illuminate missing data or an absent confirmed report", () => {
    expect(coverage(null, "heart")).toBe(false);
    expect(coverage(report, "heart")).toBe(true);
    expect(coverage(report, "kidney")).toBe(false);
    expect(coverage(report, "metabolic")).toBe(false);
  });
  it("isolates system plans and deduplicates the combined plan", () => {
    expect(recommendations(report, "heart").map(x => x.code)).toEqual(["bp", "lipids"]);
    expect(recommendations(report, "metabolic").map(x => x.code)).toEqual(["glucose"]);
    expect(recommendations(report, "kidney").map(x => x.code)).toEqual(["kidney"]);
    expect(recommendations(report, "all")).toHaveLength(4);
  });
  it("preserves a clinical referral rather than implying no follow-up", () => {
    const clinical = { ...report, recommendations: [{ code: "clinical", title: "先评估" }] } as Report;
    for (const key of ["heart", "metabolic", "kidney", "all"] as const) {
      expect(recommendations(clinical, key).map(x => x.code)).toEqual(["clinical"]);
    }
  });
});

export type Visit = {
  date: string; age: number | null; sbp: number | null; total_c: number | null; hdl_c: number | null;
  chol_unit: "mmol/L" | "mg/dL"; bmi: number | null; egfr: number | null;
  dm: boolean | null; smoking: boolean | null; bp_tx: boolean | null; statin: boolean | null;
  hba1c: number | null; fasting_glucose: number | null;
  glucose_status: "normal" | "prediabetes" | "diabetes" | "unknown";
};
export type Intake = {
  label: string; sex: "female" | "male"; known_cvd: boolean | null;
  pregnant: boolean | null; symptomatic: boolean | null;
  source: "synthetic" | "manual" | "public_dataset";
  source_note: string; as_of: string; visits: Visit[];
};
export type Report = {
  id?: string; created_at?: string; input: Intake;
  risk: null | { variant: string; version: string; horizons: Record<string, Record<string, number>> };
  blockers: string[]; planning_window: string[]; rules_version: string;
  upstream: string; review_status: string; limitations: string[];
  sources: Record<string, { title: string; url: string }>;
  recommendations: { code: string; title: string; decision: string; reason: string;
    source: string; basis: string; due_date: string | null; within_next_year: boolean | null }[];
  trends: { key: string; label: string; unit: string;
    points: { date: string; value: number }[]; change: number | null }[];
};

export type LesionMatchStatus = "MATCHED" | "NEED_REVIEW" | "NEW_LESION";

export interface LesionMatchDecision {
  current_lesion_id: string;
  candidate_track_id: string | null;
  matched_track_id: string | null;
  confidence: number;
  status: LesionMatchStatus;
  component_scores: Record<string, number>;
  weighted_contributions: Record<string, number>;
  reasons: string[];
}

export interface LesionTrendPoint {
  lesion_id: string;
  exam_date: string;
  size_mm: number | null;
  grade: string | null;
  absolute_change_from_previous: number | null;
  months_from_previous: number | null;
}

export interface LesionTrendResult {
  track_id: string;
  observations: LesionTrendPoint[];
  absolute_size_change: number | null;
  relative_size_change: number | null;
  growth_rate: number | null;
  grade_change:
    | "UNCHANGED"
    | "INCREASED"
    | "DECREASED"
    | "CHANGED"
    | "UNKNOWN";
  continuous_occurrences: number;
  months_since_last_exam: number;
  new_lesion: boolean;
  disappeared: boolean;
  stable: boolean;
  growing: boolean;
  shrinking: boolean;
  reasons: string[];
  trend_version: string;
}

export interface LesionDemoAnalysis {
  is_demo: boolean;
  demo_label: "DEMO DATA";
  patient_code: string;
  track_id: string;
  canonical_location: string;
  matches: LesionMatchDecision[];
  trend: LesionTrendResult;
  disclaimer: string;
}

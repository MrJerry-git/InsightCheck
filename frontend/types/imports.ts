export type ImportValidation = {
  valid: boolean;
  counts: Record<string, number>;
  issues: { table: string; row: number; field: string; message: string }[];
};

export type ImportResult = {
  batch_id: string;
  created: Record<string, number>;
  reused: Record<string, number>;
};

export type ImportedPatient = {
  id: string;
  anonymous_code: string;
  source_kind: string;
  source_version: string;
};

export type ImportedHistory = {
  anonymous_code: string;
  source_kind: string;
  source_version: string;
  truncated: boolean;
  checks: {
    id: string;
    check_date: string;
    event_time: string | null;
    observations: {
      id: string;
      name: string;
      value: number | null;
      unit: string;
      event_time: string;
      available_at: null;
      status: string;
    }[];
  }[];
};

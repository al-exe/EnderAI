export type V2DocumentSegment = {
  text: string;
  evidence_anchor_id?: string | null;
};

export type V2DocumentParagraph = {
  segments: V2DocumentSegment[];
};

export type V2DocumentDetailsSection = {
  anchor_id: string;
  markdown: string;
};

export type V2Document = {
  id: string;
  owner_id?: string;
  organization_id?: string | null;
  visibility?: "private" | "organization";
  title: string;
  description: string;
  human_summary: string;
  ai_generated_summary: string;
  collaborators: string[];
  main_body: V2DocumentParagraph[];
  details_file_name: string;
  details_markdown_sections: V2DocumentDetailsSection[];
  is_demo: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type V2DocumentsList = {
  data: V2Document[];
  count: number;
};

export type V2DocumentUpdate = Partial<{
  title: string;
  description: string;
  human_summary: string;
  ai_generated_summary: string;
  collaborators: string[];
  main_body: V2DocumentParagraph[];
  details_file_name: string;
  details_markdown_sections: V2DocumentDetailsSection[];
  visibility: "private" | "organization";
}>;

/**
 * Request inputs distilled into the shape the scoring engine and self-heal
 * planner consume. Keep this decoupled from the MCP tool input shape — tools
 * normalize their args into this before calling scoring.
 */
export type MatchRequest = {
  request_summary: string;
  title?: string;
  goal?: string;
  acceptance_criteria?: string;
  collaborators: string[];
  files: string[];
  symbols: string[];
  errors: string[];
  contexts: string[];
  visibility?: "private" | "organization";
  /** Optional explicit reuse window in seconds. Defaults to 30 days. */
  reuse_within_seconds?: number;
  /** When true, scoring should not be invoked; caller will create a fresh doc. */
  force_new?: boolean;
  /** Optional explicit document id to reuse without scoring. */
  document_id?: string;
  /** Whether the request is operating in demo mode. */
  demo?: boolean;
};

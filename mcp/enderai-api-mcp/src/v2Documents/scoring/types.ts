import type { V2Document, MatchRequest } from "../types.js";

export type SignalName =
  // Positive signals — sum to 100 by convention when each fires at strength 1.
  | "title-overlap"
  | "file-overlap"
  | "symbol-overlap"
  | "error-overlap"
  | "anchor-overlap"
  | "collaborator-overlap"
  | "recency"
  | "intent-phrase"
  // Conflicts — negative weights, can pull total below zero before clamping.
  | "tenant-conflict"
  | "repo-conflict"
  | "error-family-conflict"
  | "terminal-state-conflict";

export type SignalKind = "positive" | "conflict";

export type SignalResult = {
  name: SignalName;
  kind: SignalKind;
  /**
   * Strength in [0, 1] for positives, [0, 1] for conflicts (where 1 = strongest
   * conflict). The engine applies the configured weight (negative for
   * conflicts) so signal authors never need to think about sign.
   */
  strength: number;
  reason: string;
  evidence?: unknown;
};

export type SignalScorer = (
  candidate: V2Document,
  request: MatchRequest,
) => SignalResult;

export type ScoredSignal = SignalResult & {
  weight: number;
  contribution: number;
};

export type ConfidenceBand = "high" | "medium" | "low";

export type CongruenceScore = {
  total: number;
  rawTotal: number;
  band: ConfidenceBand;
  signals: ScoredSignal[];
  /**
   * Names of positive signals whose strength was below the
   * `weakSignalThreshold` in config. Consumed by the self-heal planner so a
   * reused document can be patched to represent the parts of the new request
   * it didn't already cover.
   */
  weakSignals: SignalName[];
  /** Conflict signals that fired (any with strength > 0). */
  conflicts: ScoredSignal[];
};

export type ScoredCandidate = {
  candidate: V2Document;
  score: CongruenceScore;
};

export type DecisionAction = "reuse" | "create";

export type Decision = {
  action: DecisionAction;
  documentId?: string;
  score?: CongruenceScore;
  candidates: ScoredCandidate[];
  reason: string;
};

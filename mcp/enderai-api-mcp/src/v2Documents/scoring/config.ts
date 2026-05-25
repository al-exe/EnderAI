import { DEFAULT_SIGNALS } from "./signals.js";
import type { ConfidenceBand, SignalName, SignalScorer } from "./types.js";

export type ScoringConfig = {
  /** Per-signal weights. Positive for positive signals, negative for conflicts. */
  weights: Record<SignalName, number>;
  bands: {
    high: number;
    medium: number;
  };
  /** Below this strength a positive signal is considered "weak" → self-heal. */
  weakSignalThreshold: number;
  /**
   * Ambiguous-tie margin. When the top two scored candidates are within this
   * many points and neither sits in the high band, treat the choice as
   * ambiguous (decide.ts will prefer create).
   */
  ambiguousLeadMargin: number;
  signals: readonly SignalScorer[];
};

/**
 * Default weights. Positive weights sum to 100 — that means a perfectly
 * matched candidate scores 100 before any conflict penalty. Conflicts are
 * negative weights so the same single calculation handles both pulls.
 */
export const DEFAULT_CONFIG: ScoringConfig = {
  weights: {
    "title-overlap": 25,
    "file-overlap": 20,
    "symbol-overlap": 10,
    "error-overlap": 15,
    "anchor-overlap": 5,
    "collaborator-overlap": 5,
    "recency": 10,
    "intent-phrase": 10,
    "tenant-conflict": -60,
    "repo-conflict": -30,
    "error-family-conflict": -25,
    "terminal-state-conflict": -25,
  },
  bands: {
    high: 70,
    medium: 45,
  },
  weakSignalThreshold: 0.3,
  ambiguousLeadMargin: 10,
  signals: DEFAULT_SIGNALS,
};

export function bandFor(total: number, config: ScoringConfig = DEFAULT_CONFIG): ConfidenceBand {
  if (total >= config.bands.high) return "high";
  if (total >= config.bands.medium) return "medium";
  return "low";
}

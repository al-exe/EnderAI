export {
  DEFAULT_SIGNALS,
  scoreTitleOverlap,
  scoreFileOverlap,
  scoreSymbolOverlap,
  scoreErrorOverlap,
  scoreAnchorOverlap,
  scoreCollaboratorOverlap,
  scoreRecency,
  scoreIntentPhrase,
  scoreTenantConflict,
  scoreRepoConflict,
  scoreErrorFamilyConflict,
  scoreTerminalStateConflict,
  tokenize,
} from "./signals.js";
export { DEFAULT_CONFIG, bandFor, type ScoringConfig } from "./config.js";
export { scoreCongruence, decide, type DecideArgs } from "./engine.js";
export type {
  CongruenceScore,
  Decision,
  DecisionAction,
  ScoredCandidate,
  ScoredSignal,
  SignalName,
  SignalKind,
  SignalResult,
  SignalScorer,
  ConfidenceBand,
} from "./types.js";

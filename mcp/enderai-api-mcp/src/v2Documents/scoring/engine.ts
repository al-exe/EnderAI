import type { V2Document, MatchRequest } from "../types.js";
import { DEFAULT_CONFIG, bandFor, type ScoringConfig } from "./config.js";
import type {
  CongruenceScore,
  Decision,
  ScoredCandidate,
  ScoredSignal,
  SignalName,
} from "./types.js";

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function scoreCongruence(
  candidate: V2Document,
  request: MatchRequest,
  config: ScoringConfig = DEFAULT_CONFIG,
): CongruenceScore {
  const scored: ScoredSignal[] = [];
  let raw = 0;
  for (const scorer of config.signals) {
    const result = scorer(candidate, request);
    const weight = config.weights[result.name] ?? 0;
    const contribution = result.strength * weight;
    raw += contribution;
    scored.push({ ...result, weight, contribution });
  }

  const total = Math.round(clamp(raw, 0, 100));
  const band = bandFor(total, config);
  const weakSignals: SignalName[] = scored
    .filter(
      (s) =>
        s.kind === "positive" &&
        s.weight > 0 &&
        s.strength < config.weakSignalThreshold,
    )
    .map((s) => s.name);
  const conflicts = scored.filter((s) => s.kind === "conflict" && s.strength > 0);

  return {
    total,
    rawTotal: Math.round(raw),
    band,
    signals: scored,
    weakSignals,
    conflicts,
  };
}

export type DecideArgs = {
  candidates: V2Document[];
  request: MatchRequest;
  config?: ScoringConfig;
};

/**
 * Pick reuse-or-create. Rules:
 *  - explicit document_id is honoured by the caller (not this function)
 *  - force_new is honoured by the caller
 *  - if no candidate scores >= medium band → create
 *  - if top candidate is in high band → reuse, even if a second is close
 *  - if top is medium AND lead margin over runner-up < ambiguousLeadMargin → create
 *  - else reuse the top
 */
export function decide(args: DecideArgs): Decision {
  const config = args.config ?? DEFAULT_CONFIG;
  const scored: ScoredCandidate[] = args.candidates
    .map((candidate) => ({
      candidate,
      score: scoreCongruence(candidate, args.request, config),
    }))
    .sort((a, b) => b.score.total - a.score.total);

  if (scored.length === 0) {
    return {
      action: "create",
      candidates: [],
      reason: "No candidate documents to score",
    };
  }

  const top = scored[0];
  if (top.score.band === "low") {
    return {
      action: "create",
      candidates: scored,
      reason: `Best candidate scored ${top.score.total} (low band). Creating fresh document.`,
    };
  }

  if (top.score.band === "high") {
    return {
      action: "reuse",
      documentId: top.candidate.id,
      score: top.score,
      candidates: scored,
      reason: `Top candidate scored ${top.score.total} (high band). Reusing.`,
    };
  }

  // medium band — need a clear lead and no fired conflicts.
  if (top.score.conflicts.length > 0) {
    return {
      action: "create",
      candidates: scored,
      reason: `Top candidate scored ${top.score.total} (medium) but ${top.score.conflicts.length} conflict signal${top.score.conflicts.length === 1 ? "" : "s"} fired: ${top.score.conflicts.map((c) => c.name).join(", ")}`,
    };
  }
  if (scored.length >= 2) {
    const runnerUp = scored[1];
    const margin = top.score.total - runnerUp.score.total;
    if (margin < config.ambiguousLeadMargin) {
      return {
        action: "create",
        candidates: scored,
        reason: `Top two candidates are within ${margin} points (${top.score.total} vs ${runnerUp.score.total}); ambiguous. Creating fresh document.`,
      };
    }
  }
  return {
    action: "reuse",
    documentId: top.candidate.id,
    score: top.score,
    candidates: scored,
    reason: `Top candidate scored ${top.score.total} (medium) with clear lead and no conflicts. Reusing.`,
  };
}

import { describe, expect, it } from "vitest";

import {
  DEFAULT_CONFIG,
  bandFor,
  decide,
  scoreAnchorOverlap,
  scoreCollaboratorOverlap,
  scoreCongruence,
  scoreErrorFamilyConflict,
  scoreErrorOverlap,
  scoreFileOverlap,
  scoreIntentPhrase,
  scoreRecency,
  scoreRepoConflict,
  scoreSymbolOverlap,
  scoreTenantConflict,
  scoreTerminalStateConflict,
  scoreTitleOverlap,
  tokenize,
} from "../src/v2Documents/scoring/index.js";
import type {
  MatchRequest,
  V2Document,
} from "../src/v2Documents/types.js";

function makeRequest(partial: Partial<MatchRequest> = {}): MatchRequest {
  return {
    request_summary: "investigate stale bridge routing for XYZ Corp",
    title: undefined,
    goal: undefined,
    acceptance_criteria: undefined,
    collaborators: [],
    files: [],
    symbols: [],
    errors: [],
    contexts: [],
    demo: false,
    ...partial,
  };
}

function makeDoc(partial: Partial<V2Document> = {}): V2Document {
  const now = new Date().toISOString();
  return {
    id: "11111111-1111-1111-1111-111111111111",
    title: "Latest Stale Network Bridge Issue",
    description: "Customer-impact investigation",
    human_summary: "Stale bridge routing after deploy.",
    ai_generated_summary: "",
    collaborators: ["Alex Lee", "Nia Patel"],
    main_body: [
      {
        segments: [
          { text: "After the bridge-controller deploy, " },
          {
            text: "XYZ Corp users hit stale bridge routing",
            evidence_anchor_id: "affected-users",
          },
        ],
      },
    ],
    details_file_name: "latest-stale-network-bridge-issue.details.md",
    details_markdown_sections: [
      {
        anchor_id: "affected-users",
        markdown: "## Affected Users\nXYZ Corp tenants reported intermittent 502s.",
      },
    ],
    is_demo: false,
    created_at: now,
    updated_at: now,
    ...partial,
  };
}

describe("tokenize", () => {
  it("filters stopwords and short tokens", () => {
    expect(tokenize("The quick brown fox is on the table")).toEqual([
      "quick",
      "brown",
      "fox",
      "table",
    ]);
  });
  it("returns empty for falsy input", () => {
    expect(tokenize(undefined)).toEqual([]);
    expect(tokenize("")).toEqual([]);
  });
});

describe("positive signals", () => {
  it("scoreTitleOverlap awards 1.0 on exact match", () => {
    const doc = makeDoc();
    const req = makeRequest({ title: doc.title });
    const result = scoreTitleOverlap(doc, req);
    expect(result.strength).toBe(1);
    expect(result.reason).toMatch(/Exact title match/);
  });
  it("scoreTitleOverlap falls back to request_summary tokens", () => {
    const doc = makeDoc();
    const req = makeRequest({ request_summary: "stale bridge routing" });
    const result = scoreTitleOverlap(doc, req);
    expect(result.strength).toBeGreaterThan(0);
  });

  it("scoreFileOverlap is zero with empty request files", () => {
    expect(scoreFileOverlap(makeDoc(), makeRequest()).strength).toBe(0);
  });
  it("scoreFileOverlap counts mentioned files", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        {
          anchor_id: "files",
          markdown: "- `infra/network/bridge-refresh.sh`",
        },
      ],
    });
    const req = makeRequest({
      files: ["infra/network/bridge-refresh.sh", "unrelated/file.ts"],
    });
    const result = scoreFileOverlap(doc, req);
    expect(result.strength).toBeCloseTo(0.5);
  });

  it("scoreSymbolOverlap matches case-insensitively", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "refers to BridgeController class" },
      ],
    });
    const req = makeRequest({ symbols: ["bridgeController"] });
    expect(scoreSymbolOverlap(doc, req).strength).toBe(1);
  });

  it("scoreErrorOverlap detects mentioned errors", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "Saw 502 Bad Gateway from upstream." },
      ],
    });
    const req = makeRequest({ errors: ["502 Bad Gateway"] });
    expect(scoreErrorOverlap(doc, req).strength).toBe(1);
  });

  it("scoreAnchorOverlap matches request hints against anchor IDs", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "affected-users", markdown: "" },
        { anchor_id: "validated-fix", markdown: "" },
      ],
    });
    const req = makeRequest({ contexts: ["affected users follow-up"] });
    expect(scoreAnchorOverlap(doc, req).strength).toBeGreaterThan(0);
  });

  it("scoreCollaboratorOverlap is zero with no overlap", () => {
    const doc = makeDoc({ collaborators: ["Alice"] });
    const req = makeRequest({ collaborators: ["Bob"] });
    expect(scoreCollaboratorOverlap(doc, req).strength).toBe(0);
  });

  it("scoreRecency awards 1.0 for just-updated docs", () => {
    const doc = makeDoc({ updated_at: new Date().toISOString() });
    expect(scoreRecency(doc, makeRequest()).strength).toBeCloseTo(1, 1);
  });
  it("scoreRecency awards 0 when outside window", () => {
    const old = new Date(Date.now() - 1000 * 60 * 60 * 24 * 200).toISOString();
    expect(scoreRecency(makeDoc({ updated_at: old }), makeRequest()).strength).toBe(0);
  });

  it("scoreIntentPhrase picks up continuation phrases", () => {
    const req = makeRequest({
      request_summary: "continuing the same incident from yesterday",
    });
    expect(scoreIntentPhrase(makeDoc(), req).strength).toBeGreaterThan(0);
  });
});

describe("conflict signals", () => {
  it("scoreTenantConflict fires when tenants are disjoint", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "tenant: xyz" },
      ],
    });
    const req = makeRequest({ contexts: ["tenant: acme"] });
    const result = scoreTenantConflict(doc, req);
    expect(result.strength).toBe(1);
  });
  it("scoreTenantConflict is zero when tenants match", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "tenant: xyz" },
      ],
    });
    const req = makeRequest({ contexts: ["tenant: xyz"] });
    expect(scoreTenantConflict(doc, req).strength).toBe(0);
  });

  it("scoreRepoConflict fires on disjoint top-dirs", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "infra/network/bridge.sh" },
      ],
    });
    const req = makeRequest({ files: ["frontend/src/app.tsx"] });
    expect(scoreRepoConflict(doc, req).strength).toBe(1);
  });

  it("scoreErrorFamilyConflict fires on disjoint error families", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "Saw a timeout reading from upstream." },
      ],
    });
    const req = makeRequest({ errors: ["403 forbidden"] });
    expect(scoreErrorFamilyConflict(doc, req).strength).toBe(1);
  });

  it("scoreTerminalStateConflict fires when doc is terminal and request is new", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "outcome", markdown: "## Outcome\nstatus: done" },
      ],
    });
    const result = scoreTerminalStateConflict(
      doc,
      makeRequest({ request_summary: "brand new investigation" }),
    );
    expect(result.strength).toBe(1);
  });
  it("scoreTerminalStateConflict is zero when request continues prior work", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "outcome", markdown: "## Outcome\nstatus: done" },
      ],
    });
    const result = scoreTerminalStateConflict(
      doc,
      makeRequest({ request_summary: "continuing the prior investigation" }),
    );
    expect(result.strength).toBe(0);
  });
});

describe("scoreCongruence composition", () => {
  it("returns total in [0, 100] and lists weak signals", () => {
    const doc = makeDoc();
    const req = makeRequest({
      title: doc.title,
      files: ["unrelated/file.ts"],
      errors: ["something we never saw"],
    });
    const score = scoreCongruence(doc, req);
    expect(score.total).toBeGreaterThanOrEqual(0);
    expect(score.total).toBeLessThanOrEqual(100);
    expect(score.weakSignals).toEqual(
      expect.arrayContaining(["file-overlap", "error-overlap"]),
    );
  });

  it("conflicts pull total down before clamping", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "x", markdown: "tenant: xyz\n## Outcome\nstatus: done" },
      ],
    });
    const req = makeRequest({
      title: doc.title,
      contexts: ["tenant: acme"],
      request_summary: "fresh unrelated work",
    });
    const score = scoreCongruence(doc, req);
    expect(score.conflicts.length).toBeGreaterThanOrEqual(2);
    expect(score.total).toBeLessThan(DEFAULT_CONFIG.bands.medium);
  });
});

describe("bandFor", () => {
  it("maps total to the right band", () => {
    expect(bandFor(80)).toBe("high");
    expect(bandFor(60)).toBe("medium");
    expect(bandFor(10)).toBe("low");
  });
});

describe("decide()", () => {
  it("returns create when there are no candidates", () => {
    expect(decide({ candidates: [], request: makeRequest() }).action).toBe("create");
  });

  it("reuses on high-band match", () => {
    const doc = makeDoc({
      collaborators: ["Alex Lee", "Nia Patel"],
      details_markdown_sections: [
        {
          anchor_id: "affected-users",
          markdown:
            "## Affected\nFiles `infra/network/bridge-refresh.sh` and `ops/runbooks/bridge.md`. Saw 502 timeout repeatedly.",
        },
      ],
    });
    const req = makeRequest({
      title: doc.title,
      request_summary: "continuing the stale bridge routing investigation",
      files: ["infra/network/bridge-refresh.sh", "ops/runbooks/bridge.md"],
      errors: ["502 timeout"],
      collaborators: ["Alex Lee"],
    });
    const decision = decide({ candidates: [doc], request: req });
    expect(decision.action).toBe("reuse");
    expect(decision.documentId).toBe(doc.id);
    expect(decision.score?.band).toBe("high");
  });

  it("creates when top scores low", () => {
    const doc = makeDoc({ title: "Totally Unrelated Topic" });
    const decision = decide({
      candidates: [doc],
      request: makeRequest({ request_summary: "investigate frontend rendering bug" }),
    });
    expect(decision.action).toBe("create");
  });

  it("creates when top two medium candidates are close", () => {
    const sharedBody = {
      details_markdown_sections: [
        {
          anchor_id: "files",
          markdown:
            "Touched `infra/network/bridge-refresh.sh` and `ops/runbooks/bridge.md`. Encountered timeout error.",
        },
      ],
    };
    const a = makeDoc({
      id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      title: "Network Bridge One",
      ...sharedBody,
    });
    const b = makeDoc({
      id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      title: "Network Bridge Two",
      ...sharedBody,
    });
    const decision = decide({
      candidates: [a, b],
      request: makeRequest({
        request_summary: "network bridge investigation",
        files: ["infra/network/bridge-refresh.sh", "ops/runbooks/bridge.md"],
        errors: ["timeout"],
      }),
    });
    expect(decision.action).toBe("create");
    expect(decision.reason).toMatch(/ambiguous|within/i);
  });

  it("creates when top is medium but a conflict fires", () => {
    // Build a candidate whose positive signals would clear high band, then
    // attach a terminal-state marker. The request scores medium overall and
    // the conflict path forces create.
    const doc = makeDoc({
      title: "Network Bridge Issue",
      details_markdown_sections: [
        {
          anchor_id: "files",
          markdown:
            "Files: `infra/network/bridge-refresh.sh`, `ops/runbooks/bridge.md`. Saw timeout failures.",
        },
        { anchor_id: "outcome", markdown: "## Outcome\nstatus: done" },
      ],
    });
    const decision = decide({
      candidates: [doc],
      request: makeRequest({
        request_summary: "brand-new bridge investigation",
        title: "Network Bridge Issue",
        files: ["infra/network/bridge-refresh.sh", "ops/runbooks/bridge.md"],
        errors: ["timeout"],
      }),
    });
    expect(decision.action).toBe("create");
    expect(decision.reason).toMatch(/conflict/i);
  });
});

import { describe, expect, it } from "vitest";

import { planSelfHeal } from "../src/v2Documents/selfHeal.js";
import { scoreCongruence } from "../src/v2Documents/scoring/engine.js";
import type { MatchRequest, V2Document } from "../src/v2Documents/types.js";

function makeRequest(partial: Partial<MatchRequest> = {}): MatchRequest {
  return {
    request_summary: "investigate stale bridge routing for XYZ Corp",
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
    id: "doc-1",
    title: "Latest Stale Network Bridge Issue",
    description: "Customer-impact investigation",
    human_summary: "Stale bridge routing after deploy.",
    ai_generated_summary: "Bridge routing summary.",
    collaborators: ["Alex Lee"],
    main_body: [],
    details_file_name: "bridge.details.md",
    details_markdown_sections: [
      { anchor_id: "affected-users", markdown: "## Affected" },
    ],
    is_demo: false,
    created_at: now,
    updated_at: now,
    ...partial,
  };
}

describe("planSelfHeal", () => {
  it("populates missing description and ai_generated_summary", () => {
    const doc = makeDoc({ description: "", ai_generated_summary: "" });
    const { patch, appliedFixes } = planSelfHeal({
      document: doc,
      request: makeRequest({ goal: "fix tenant bridge cache" }),
    });
    expect(patch.description).toBe("fix tenant bridge cache");
    expect(patch.ai_generated_summary).toMatch(/Agent-maintained/);
    expect(appliedFixes).toEqual(
      expect.arrayContaining([
        "populated missing description",
        "populated missing ai_generated_summary",
      ]),
    );
  });

  it("sets a derived details_file_name when missing", () => {
    const doc = makeDoc({ details_file_name: "" });
    const { patch } = planSelfHeal({ document: doc, request: makeRequest() });
    expect(patch.details_file_name).toBe(
      "latest-stale-network-bridge-issue.details.md",
    );
  });

  it("merges new collaborators without duplicates", () => {
    const doc = makeDoc({ collaborators: ["Alex Lee"] });
    const { patch } = planSelfHeal({
      document: doc,
      request: makeRequest({ collaborators: ["alex lee", "Nia Patel"] }),
    });
    expect(patch.collaborators).toEqual(["Alex Lee", "Nia Patel"]);
  });

  it("normalizes Details anchor IDs that are missing or duplicate", () => {
    const doc = makeDoc({
      details_markdown_sections: [
        { anchor_id: "", markdown: "first" },
        { anchor_id: "shared", markdown: "second" },
        { anchor_id: "shared", markdown: "third" },
      ],
    });
    const { patch, appliedFixes } = planSelfHeal({
      document: doc,
      request: makeRequest(),
    });
    expect(appliedFixes).toContain("normalized Details anchor IDs");
    const anchors = patch.details_markdown_sections!.map((s) => s.anchor_id);
    expect(new Set(anchors).size).toBe(3);
  });

  it("drops Summary anchors pointing at missing Details", () => {
    const doc = makeDoc({
      main_body: [
        {
          segments: [
            { text: "anchored claim", evidence_anchor_id: "missing-anchor" },
            { text: " plain text" },
          ],
        },
      ],
    });
    const { patch, appliedFixes } = planSelfHeal({
      document: doc,
      request: makeRequest(),
    });
    expect(appliedFixes).toContain(
      "dropped Summary anchors pointing at missing Details sections",
    );
    const first = patch.main_body![0].segments[0];
    expect(first.evidence_anchor_id).toBeUndefined();
  });

  it("adds a Current Work section when file-overlap is weak", () => {
    const doc = makeDoc();
    const request = makeRequest({
      files: ["infra/network/bridge-refresh.sh"],
    });
    const score = scoreCongruence(doc, request);
    expect(score.weakSignals).toContain("file-overlap");
    const { patch, appliedFixes } = planSelfHeal({
      document: doc,
      request,
      score,
    });
    expect(
      appliedFixes.some((f) => f.startsWith("added Current Work Details section")),
    ).toBe(true);
    const newSection = patch.details_markdown_sections!.find((s) =>
      s.anchor_id.startsWith("current-work-"),
    );
    expect(newSection?.markdown).toContain("infra/network/bridge-refresh.sh");
  });

  it("does not rewrite title in isolation", () => {
    const doc = makeDoc();
    const { patch } = planSelfHeal({
      document: doc,
      request: makeRequest({ title: "New Title Just Because" }),
    });
    expect(patch.title).toBeUndefined();
  });
});

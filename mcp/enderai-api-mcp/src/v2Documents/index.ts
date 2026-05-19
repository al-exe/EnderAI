export {
  beginDocument,
  updateDocument,
  finishDocument,
  type BeginDocumentArgs,
  type BeginDocumentResult,
  type UpdateDocumentArgs,
  type UpdateDocumentResult,
  type FinishDocumentArgs,
  type FinishDocumentResult,
  type ToolEnv,
} from "./tools.js";
export {
  createActiveDocumentState,
  type ActiveDocumentState,
} from "./active.js";
export type {
  V2Document,
  V2DocumentParagraph,
  V2DocumentSegment,
  V2DocumentDetailsSection,
  V2DocumentsList,
  V2DocumentUpdate,
  MatchRequest,
} from "./types.js";
export { planSelfHeal, type SelfHealResult } from "./selfHeal.js";
export * from "./scoring/index.js";

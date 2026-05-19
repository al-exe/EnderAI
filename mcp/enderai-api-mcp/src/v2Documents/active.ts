export type ActiveDocumentState = {
  documentId?: string;
  title?: string;
  startedAt?: string;
  lastUpdatedAt?: string;
  demo?: boolean;
};

export function createActiveDocumentState(): ActiveDocumentState {
  return {};
}

export function setActiveDocument(
  state: ActiveDocumentState,
  params: { documentId: string; title: string; demo?: boolean },
): void {
  const now = new Date().toISOString();
  state.documentId = params.documentId;
  state.title = params.title;
  state.demo = params.demo;
  if (!state.startedAt) state.startedAt = now;
  state.lastUpdatedAt = now;
}

export function touchActiveDocument(state: ActiveDocumentState): void {
  state.lastUpdatedAt = new Date().toISOString();
}

export function clearActiveDocument(state: ActiveDocumentState): void {
  delete state.documentId;
  delete state.title;
  delete state.startedAt;
  delete state.lastUpdatedAt;
  delete state.demo;
}

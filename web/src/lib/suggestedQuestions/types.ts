/** Mirrors `PersonSuggestions` in
 * backend/onyx/server/features/suggested_questions/models.py. */
export type SuggestionsState = "ready" | "preparing" | "no_documents";

export interface ShownQuestion {
  id: string;
  message: string;
  /** From the person's own documents; for analytics, it looks the same. */
  private: boolean;
}

export interface PersonSuggestions {
  questions: ShownQuestion[];
  state: SuggestionsState;
}

export interface IndexAttemptError {
  id: number;
  index_attempt_id: number;
  batch_number: number;
  doc_summaries: DocumentErrorSummary[];
  error_msg: string;
  traceback: string;
  time_created: string;
}

export interface DocumentErrorSummary {
  id: string;
  semantic_id: string;
  section_link: string;
}

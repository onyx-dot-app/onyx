/**
 * The agent's questions - the question card template. The card shares the
 * approval card's frame, header, actions and records.
 */

import { html, nothing, TemplateResult } from "lit";
import { keyed } from "lit/directives/keyed.js";
import type { ToolQuestionRequest } from "@/types/api-types";
import {
  choiceAnswer,
  draftAnswers,
  draftChoice,
  QuestionChoice,
  QuestionDraft,
  QuestionEntry,
  questionRecords,
  QuestionResolution,
} from "@/services/questions";
import { ICON_CHECK, ICON_CLOCK, ICON_LOADER } from "@/services/approval-card";

const TITLE = "The agent has a question";
const FAILED = "Could not submit your answer. Try again.";
const BACK = "Back";
const NEXT = "Next";
const SUBMIT = "Submit";

/** The widget state one card reads, and its handlers. */
export interface QuestionCardView {
  submitting: boolean;
  failed: boolean;
  draft: QuestionDraft | undefined;
  /** The question that the card shows, from 0. */
  page: number;
  onChoose: (
    request: ToolQuestionRequest,
    questionId: string,
    choice: QuestionChoice
  ) => void;
  onPage: (request: ToolQuestionRequest, page: number) => void;
  onSubmit: (request: ToolQuestionRequest) => void;
}

/**
 * A waiting request shows one question at a time, with its options and
 * "Other". A request with more questions has Back and Next, and Submit on
 * its last question. An ended request shows one line per question.
 */
export function renderQuestionCard(
  entry: QuestionEntry,
  resolution: QuestionResolution | null,
  view: QuestionCardView
): TemplateResult {
  const { request } = entry;
  const requestId = request.question_request_id;
  if (resolution !== null) {
    const records = questionRecords(request, resolution);
    return html`
      <div class="approval" data-question-request-id=${requestId}>
        <p class="sr-only" role="status">${records.join(". ")}</p>
        ${records.map(
          (record) => html`<div class="approval-record" aria-hidden="true">
            ${resolution.outcome === "answered" ? ICON_CHECK : ICON_CLOCK}
            <span title=${record}>${record}</span>
          </div>`
        )}
      </div>
    `;
  }

  const { submitting, draft, onChoose, onPage, onSubmit } = view;
  const { questions } = request;
  const page = Math.min(Math.max(view.page, 0), questions.length - 1);
  const question = questions[page]!;
  const paged = questions.length > 1;
  const last = page === questions.length - 1;
  const answers = draftAnswers(request, draft);
  const unanswered = questions.flatMap((each, index) =>
    choiceAnswer(each.id, draftChoice(draft, each.id)) ? [] : [index + 1]
  );
  const hintId =
    paged && last && unanswered.length > 0
      ? `question-unanswered-${requestId}`
      : null;
  const choice = draftChoice(draft, question.id);
  const name = JSON.stringify([requestId, question.id]);
  const note = choice && "note" in choice ? choice.note : null;
  return html`
    <div class="approval" data-question-request-id=${requestId}>
      <p class="sr-only" role="status">${TITLE}</p>
      <div class="approval-card">
        <div class="approval-header">
          <span class="approval-spinner" aria-hidden="true">${ICON_LOADER}</span>
          <span class="approval-title" title=${TITLE}>${TITLE}</span>
        </div>
        <div class="approval-body">
          ${keyed(
            question.id,
            html`
              <fieldset
                class="question"
                data-question-id=${question.id}
                ?disabled=${submitting}
              >
                <legend>
                  ${
                    paged
                      ? html`<span class="question-page"
                          >${`Question ${page + 1} of ${questions.length}`}</span
                        >`
                      : ""
                  }
                  <span class="question-header">${question.header}</span>
                  <span class="question-text">${question.question}</span>
                </legend>
                ${question.options.map(
                  (option) => html`
                    <label class="question-option">
                      <input
                        type="radio"
                        name=${name}
                        .checked=${
                          !!choice &&
                          "option" in choice &&
                          choice.option === option.label
                        }
                        @change=${() =>
                          onChoose(request, question.id, {
                            option: option.label,
                          })}
                      />
                      <span>
                        <span class="question-option-label"
                          >${option.label}</span
                        >
                        ${
                          option.description
                            ? html`<span class="question-option-description"
                                >${option.description}</span
                              >`
                            : ""
                        }
                      </span>
                    </label>
                  `
                )}
                <label class="question-option">
                  <input
                    type="radio"
                    name=${name}
                    .checked=${note !== null}
                    @change=${() =>
                      onChoose(request, question.id, { note: note ?? "" })}
                  />
                  <span class="question-option-label">Other</span>
                </label>
                ${
                  note === null
                    ? ""
                    : html`<input
                        class="question-note"
                        type="text"
                        aria-label="Your answer to ${question.header}"
                        placeholder="Type your answer"
                        .value=${note}
                        @input=${(e: InputEvent) =>
                          onChoose(request, question.id, {
                            note: (e.target as HTMLInputElement).value,
                          })}
                        @keydown=${(e: KeyboardEvent) => {
                          // As in the chat input: the host page sees only
                          // Escape.
                          if (e.key !== "Escape") e.stopPropagation();
                          // Enter that confirms an IME candidate is not a
                          // submit.
                          if (e.key !== "Enter" || e.isComposing) return;
                          e.preventDefault();
                          if (!last) onPage(request, page + 1);
                          else if (answers !== null) onSubmit(request);
                        }}
                      />`
                }
              </fieldset>
            `
          )}
          ${
            hintId === null
              ? ""
              : html`<p class="question-unanswered" id=${hintId}>
                  ${
                    unanswered.length === 1
                      ? `Answer question ${unanswered[0]} to submit.`
                      : `Answer questions ${unanswered.slice(0, -1).join(", ")} and ${unanswered[unanswered.length - 1]} to submit.`
                  }
                </p>`
          }
          ${
            view.failed
              ? html`<p class="approval-error" role="alert">${FAILED}</p>`
              : ""
          }
        </div>
        <div class="approval-actions">
          ${
            paged
              ? html`<button
                  class="approval-button"
                  ?disabled=${submitting || page === 0}
                  @click=${() => onPage(request, page - 1)}
                >
                  ${BACK}
                </button>`
              : ""
          }
          ${
            last
              ? html`<button
                  class="approval-button primary"
                  aria-describedby=${hintId ?? nothing}
                  ?disabled=${submitting || answers === null}
                  @click=${() => onSubmit(request)}
                >
                  ${SUBMIT}
                </button>`
              : html`<button
                  class="approval-button primary"
                  ?disabled=${submitting}
                  @click=${() => onPage(request, page + 1)}
                >
                  ${NEXT}
                </button>`
          }
        </div>
      </div>
    </div>
  `;
}

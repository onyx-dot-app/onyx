/**
 * Tool-call approvals - the approval card template
 */

import { html, TemplateResult } from "lit";
import type { ToolApprovalRequest } from "@/types/api-types";
import {
  ApprovalDecision,
  ApprovalEntry,
  ApprovalStatus,
  approvalRecord,
  ARGUMENT_ROWS_SHOWN,
  ArgumentRow,
  argumentRows,
} from "@/services/approvals";

export const ICON_LOADER = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M8 1.5v2M8 12.5v2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M1.5 8h2M12.5 8h2M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/></svg>`;
export const ICON_CHECK = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="12" height="12" rx="2"/><path d="M5.5 8l2 2 3-4"/></svg>`;
const ICON_X = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M12 4L4 12M4 4l8 8"/></svg>`;
export const ICON_CLOCK = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.5V8l2.5 1.5"/></svg>`;

// Rows of each request's arguments, built once instead of on each render
const argumentRowCache = new WeakMap<ToolApprovalRequest, ArgumentRow[]>();

/** The widget state one card reads, and its handlers. */
export interface ApprovalCardView {
  submitting: boolean;
  failed: boolean;
  // Expanded argument values, as `[approval id, key]` JSON, and cards that
  // show all their rows, as `[approval id]` JSON
  expanded: ReadonlySet<string>;
  onDecide: (request: ToolApprovalRequest, decision: ApprovalDecision) => void;
  onToggle: (id: string) => void;
}

/** A waiting request shows its arguments and decisions; a decided one, one line. */
export function renderApprovalCard(
  entry: ApprovalEntry,
  status: ApprovalStatus,
  view: ApprovalCardView
): TemplateResult {
  const { request } = entry;
  const { submitting, expanded, onDecide, onToggle } = view;
  const name = request.display_name || request.tool_name;
  const record = approvalRecord(status, name);
  const title = `Approval requested: ${name}`;
  const agentLabel = request.agent_name
    ? `${request.agent_name} wants to run ${name}`
    : null;
  let rows = argumentRowCache.get(request);
  if (!rows) {
    rows = argumentRows(request.arguments);
    argumentRowCache.set(request, rows);
  }
  const allRowsId = JSON.stringify([request.approval_id]);
  const allRows = expanded.has(allRowsId);
  const shownRows = allRows ? rows : rows.slice(0, ARGUMENT_ROWS_SHOWN);

  return html`
    <div class="approval" data-approval-id=${request.approval_id}>
      <p class="sr-only" role="status">${record ?? agentLabel ?? title}</p>
      ${
        record !== null
          ? html`<div class="approval-record" aria-hidden="true">
              ${
                status === "approved" || status === "approvedForSession"
                  ? ICON_CHECK
                  : status === "rejected" || status === "disabled"
                    ? ICON_X
                    : ICON_CLOCK
              }
              <span title=${record}>${record}</span>
            </div>`
          : html`<div class="approval-card">
              ${
                agentLabel === null
                  ? ""
                  : html`<p class="approval-source" title=${agentLabel}>
                      ${agentLabel}
                    </p>`
              }
              <div class="approval-header">
                <span class="approval-spinner" aria-hidden="true"
                  >${ICON_LOADER}</span
                >
                <span class="approval-title" title=${title}>${title}</span>
              </div>
              <div class="approval-body">
                ${
                  rows.length === 0
                    ? html`<p class="approval-empty">No payload.</p>`
                    : html`<dl class="approval-args">
                          ${shownRows.map((row) => {
                            const id = JSON.stringify([
                              request.approval_id,
                              row.key,
                            ]);
                            const open = expanded.has(id);
                            return html`
                              <dt title=${row.key}>${row.key}</dt>
                              <dd class=${row.mono ? "mono" : ""}>
                                <span class="arg-value"
                                  >${
                                    row.preview === null || open
                                      ? row.text
                                      : row.preview
                                  }</span
                                >${
                                  row.preview === null
                                    ? ""
                                    : html`<button
                                        class="arg-toggle"
                                        aria-expanded=${open}
                                        @click=${() => onToggle(id)}
                                      >
                                        ${open ? "Show less" : "Show more"}
                                      </button>`
                                }
                              </dd>
                            `;
                          })}
                        </dl>
                        ${
                          rows.length > ARGUMENT_ROWS_SHOWN
                            ? html`<button
                                class="arg-toggle"
                                aria-expanded=${allRows}
                                @click=${() => onToggle(allRowsId)}
                              >
                                ${
                                  allRows
                                    ? "Show fewer arguments"
                                    : `Show all ${rows.length} arguments`
                                }
                              </button>`
                            : ""
                        }`
                }
                ${
                  view.failed
                    ? html`<p class="approval-error" role="alert">
                        Could not submit your decision. Try again.
                      </p>`
                    : ""
                }
              </div>
              <div class="approval-actions">
                <button
                  class="approval-button primary"
                  ?disabled=${submitting}
                  @click=${() => onDecide(request, "approve_once")}
                >
                  Approve once
                </button>
                <button
                  class="approval-button"
                  ?disabled=${submitting}
                  title="Approve now and run this tool without asking again for the rest of this chat"
                  @click=${() => onDecide(request, "approve_session")}
                >
                  Approve for this chat
                </button>
                <button
                  class="approval-button"
                  ?disabled=${submitting}
                  @click=${() => onDecide(request, "reject")}
                >
                  Reject
                </button>
              </div>
            </div>`
      }
    </div>
  `;
}

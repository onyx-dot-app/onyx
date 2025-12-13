"use client";

import React, { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { PermissionRequest, AvatarPermissionRequestStatus } from "@/lib/types";
import {
  useIncomingPermissionRequests,
  useOutgoingPermissionRequests,
} from "@/lib/avatar";
import {
  Inbox,
  Send,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  Loader2,
  User,
  MessageSquare,
} from "lucide-react";

type TabType = "incoming" | "outgoing";

function isValidSubTab(tab: string | null): tab is TabType {
  return tab === "incoming" || tab === "outgoing";
}

export function PermissionRequests() {
  const searchParams = useSearchParams();
  const subtabParam = searchParams.get("subtab");
  const initialSubTab = isValidSubTab(subtabParam) ? subtabParam : "outgoing";
  const [activeTab, setActiveTab] = useState<TabType>(initialSubTab);

  // Update state if URL changes externally
  useEffect(() => {
    if (isValidSubTab(subtabParam) && subtabParam !== activeTab) {
      setActiveTab(subtabParam);
    }
  }, [subtabParam, activeTab]);

  return (
    <div className="flex flex-col gap-4">
      {/* Tab Navigation */}
      <div className="flex border-b border-border">
        <button
          onClick={() => setActiveTab("incoming")}
          className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-colors ${
            activeTab === "incoming"
              ? "border-accent text-accent"
              : "border-transparent text-text-subtle hover:text-text"
          }`}
        >
          <Inbox className="h-4 w-4" />
          Incoming Requests
        </button>
        <button
          onClick={() => setActiveTab("outgoing")}
          className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-colors ${
            activeTab === "outgoing"
              ? "border-accent text-accent"
              : "border-transparent text-text-subtle hover:text-text"
          }`}
        >
          <Send className="h-4 w-4" />
          My Requests
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === "incoming" ? (
        <IncomingRequestsList />
      ) : (
        <OutgoingRequestsList />
      )}
    </div>
  );
}

function IncomingRequestsList() {
  const { requests, loading, error, approve, deny } =
    useIncomingPermissionRequests();
  const [processingId, setProcessingId] = useState<number | null>(null);
  const [denyReason, setDenyReason] = useState<string>("");
  const [showDenyModal, setShowDenyModal] = useState<number | null>(null);

  const handleApprove = async (requestId: number) => {
    setProcessingId(requestId);
    try {
      await approve(requestId);
    } catch {
      // Error handled by hook
    } finally {
      setProcessingId(null);
    }
  };

  const handleDeny = async (requestId: number) => {
    setProcessingId(requestId);
    try {
      await deny(requestId, denyReason || undefined);
      setShowDenyModal(null);
      setDenyReason("");
    } catch {
      // Error handled by hook
    } finally {
      setProcessingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-error/10 border border-error text-error rounded-lg flex items-center gap-2">
        <AlertCircle className="h-5 w-5" />
        {error}
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="p-8 text-center text-text-subtle">
        <Inbox className="h-12 w-12 mx-auto mb-3 opacity-50" />
        <p>No pending permission requests</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {requests.map((request) => (
        <div
          key={request.id}
          className="bg-background-subtle p-4 rounded-lg border border-border"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <User className="h-4 w-4 text-text-subtle" />
                <span className="font-medium">{request.requester_email}</span>
                <StatusBadge status={request.status} />
              </div>

              {request.query_text && (
                <div className="bg-background p-3 rounded border border-border mb-3">
                  <div className="flex items-center gap-2 text-xs text-text-subtle mb-1">
                    <MessageSquare className="h-3 w-3" />
                    Query
                  </div>
                  <p className="text-sm">{request.query_text}</p>
                </div>
              )}

              <div className="text-xs text-text-subtle">
                Requested {formatDate(request.created_at)} • Expires{" "}
                {formatDate(request.expires_at)}
              </div>
            </div>

            {request.status === AvatarPermissionRequestStatus.PENDING && (
              <div className="flex gap-2">
                <button
                  onClick={() => handleApprove(request.id)}
                  disabled={processingId === request.id}
                  className="flex items-center gap-1 px-3 py-1.5 bg-success text-white rounded hover:bg-success/90 disabled:opacity-50 text-sm"
                >
                  {processingId === request.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <CheckCircle className="h-3 w-3" />
                  )}
                  Approve
                </button>
                <button
                  onClick={() => setShowDenyModal(request.id)}
                  disabled={processingId === request.id}
                  className="flex items-center gap-1 px-3 py-1.5 bg-error text-white rounded hover:bg-error/90 disabled:opacity-50 text-sm"
                >
                  <XCircle className="h-3 w-3" />
                  Deny
                </button>
              </div>
            )}
          </div>

          {/* Deny Modal */}
          {showDenyModal === request.id && (
            <div className="mt-4 p-4 bg-background rounded border border-border">
              <label className="block text-sm font-medium mb-2">
                Reason for denial (optional)
              </label>
              <textarea
                value={denyReason}
                onChange={(e) => setDenyReason(e.target.value)}
                placeholder="Enter a reason..."
                className="w-full px-3 py-2 border border-border rounded bg-background text-sm resize-none h-20 focus:outline-none focus:ring-2 focus:ring-accent"
              />
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => handleDeny(request.id)}
                  disabled={processingId === request.id}
                  className="px-3 py-1.5 bg-error text-white rounded text-sm hover:bg-error/90 disabled:opacity-50"
                >
                  {processingId === request.id ? "Denying..." : "Confirm Deny"}
                </button>
                <button
                  onClick={() => {
                    setShowDenyModal(null);
                    setDenyReason("");
                  }}
                  className="px-3 py-1.5 bg-background-subtle border border-border rounded text-sm hover:bg-hover"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function OutgoingRequestsList() {
  const { requests, loading, error } = useOutgoingPermissionRequests();
  const [expandedAnswers, setExpandedAnswers] = useState<Set<number>>(
    new Set()
  );

  const toggleAnswer = (requestId: number) => {
    setExpandedAnswers((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(requestId)) {
        newSet.delete(requestId);
      } else {
        newSet.add(requestId);
      }
      return newSet;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-error/10 border border-error text-error rounded-lg flex items-center gap-2">
        <AlertCircle className="h-5 w-5" />
        {error}
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="p-8 text-center text-text-subtle">
        <Send className="h-12 w-12 mx-auto mb-3 opacity-50" />
        <p>You haven't made any permission requests</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {requests.map((request) => (
        <div
          key={request.id}
          className="bg-background-subtle p-4 rounded-lg border border-border"
        >
          <div className="flex items-center gap-2 mb-2">
            <User className="h-4 w-4 text-text-subtle" />
            <span className="font-medium">{request.avatar_user_email}</span>
            <StatusBadge status={request.status} />
          </div>

          {request.query_text && (
            <div className="bg-background p-3 rounded border border-border mb-3">
              <div className="flex items-center gap-2 text-xs text-text-subtle mb-1">
                <MessageSquare className="h-3 w-3" />
                Your Query
              </div>
              <p className="text-sm">{request.query_text}</p>
            </div>
          )}

          {/* Show View Answer button for approved requests */}
          {request.status === AvatarPermissionRequestStatus.APPROVED &&
            request.cached_answer && (
              <div className="mb-3">
                <button
                  onClick={() => toggleAnswer(request.id)}
                  className="flex items-center gap-2 px-3 py-1.5 bg-success/10 text-success border border-success/30 rounded hover:bg-success/20 transition-colors text-sm"
                >
                  <CheckCircle className="h-4 w-4" />
                  {expandedAnswers.has(request.id)
                    ? "Hide Answer"
                    : "View Answer"}
                </button>

                {expandedAnswers.has(request.id) && (
                  <div className="mt-3 bg-background p-4 rounded border border-success/30">
                    <div className="text-xs font-medium text-success mb-2">
                      Approved Answer
                    </div>
                    <div className="text-sm whitespace-pre-wrap">
                      {request.cached_answer}
                    </div>

                    {request.cached_search_doc_ids &&
                      request.cached_search_doc_ids.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-border">
                          <div className="text-xs font-medium text-text-subtle mb-2">
                            Source Chunks (
                            {request.cached_search_doc_ids.length})
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {request.cached_search_doc_ids
                              .slice(0, 5)
                              .map((chunkId, idx) => (
                                <span
                                  key={idx}
                                  className="text-xs bg-background-subtle px-2 py-1 rounded border border-border"
                                >
                                  Chunk #{chunkId}
                                </span>
                              ))}
                            {request.cached_search_doc_ids.length > 5 && (
                              <span className="text-xs text-text-subtle">
                                +{request.cached_search_doc_ids.length - 5} more
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                  </div>
                )}
              </div>
            )}

          {request.denial_reason && (
            <div className="bg-error/10 p-3 rounded border border-error/50 mb-3">
              <div className="text-xs text-error mb-1">Denial Reason</div>
              <p className="text-sm">{request.denial_reason}</p>
            </div>
          )}

          <div className="text-xs text-text-subtle">
            Requested {formatDate(request.created_at)}
            {request.resolved_at &&
              ` • Resolved ${formatDate(request.resolved_at)}`}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: AvatarPermissionRequestStatus }) {
  const config = {
    [AvatarPermissionRequestStatus.PENDING]: {
      icon: <Clock className="h-3 w-3" />,
      text: "Pending",
      className: "bg-warning/20 text-warning",
    },
    [AvatarPermissionRequestStatus.PROCESSING]: {
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      text: "Processing",
      className: "bg-accent/20 text-accent",
    },
    [AvatarPermissionRequestStatus.APPROVED]: {
      icon: <CheckCircle className="h-3 w-3" />,
      text: "Approved",
      className: "bg-success/20 text-success",
    },
    [AvatarPermissionRequestStatus.DENIED]: {
      icon: <XCircle className="h-3 w-3" />,
      text: "Denied",
      className: "bg-error/20 text-error",
    },
    [AvatarPermissionRequestStatus.EXPIRED]: {
      icon: <Clock className="h-3 w-3" />,
      text: "Expired",
      className: "bg-text-subtle/20 text-text-subtle",
    },
    [AvatarPermissionRequestStatus.NO_ANSWER]: {
      icon: <AlertCircle className="h-3 w-3" />,
      text: "No Answer",
      className: "bg-text-subtle/20 text-text-subtle",
    },
  };

  const { icon, text, className } = config[status];

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${className}`}
    >
      {icon}
      {text}
    </span>
  );
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}

export default PermissionRequests;

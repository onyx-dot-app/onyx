"use client";

import React from "react";
import { useChatSessionPermissionRequests } from "@/lib/avatar";
import { AvatarPermissionRequestStatus } from "@/lib/types";
import { CheckCircle, Clock, XCircle, User, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatSessionAvatarRequestsProps {
  chatSessionId: string | null;
}

export function ChatSessionAvatarRequests({
  chatSessionId,
}: ChatSessionAvatarRequestsProps) {
  const { requests, loading, refresh } =
    useChatSessionPermissionRequests(chatSessionId);

  // Don't render if no requests
  if (!chatSessionId || requests.length === 0) {
    return null;
  }

  // Group requests by status
  const approvedRequests = requests.filter(
    (r) => r.status === AvatarPermissionRequestStatus.APPROVED
  );
  const pendingRequests = requests.filter(
    (r) => r.status === AvatarPermissionRequestStatus.PENDING
  );
  const deniedRequests = requests.filter(
    (r) => r.status === AvatarPermissionRequestStatus.DENIED
  );

  return (
    <div className="w-full max-w-4xl mx-auto mb-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <h3 className="text-sm font-medium text-text-subtle flex items-center gap-2">
          <User className="h-4 w-4" />
          Avatar Query Results
        </h3>
        <button
          onClick={refresh}
          disabled={loading}
          className="p-1 hover:bg-background-subtle rounded transition-colors"
          title="Refresh status"
        >
          <RefreshCw
            className={cn(
              "h-4 w-4 text-text-subtle",
              loading && "animate-spin"
            )}
          />
        </button>
      </div>

      {/* Approved Requests - Show answer directly */}
      {approvedRequests.map((request) => (
        <div
          key={request.id}
          className="bg-success/5 border border-success/30 rounded-lg overflow-hidden"
        >
          <div className="px-4 py-3">
            <div className="flex items-center gap-3 mb-3">
              <CheckCircle className="h-5 w-5 text-success flex-shrink-0" />
              <div>
                <div className="text-sm font-medium">
                  Answer from {request.avatar_user_email}
                </div>
                {request.query_text && (
                  <div className="text-xs text-text-subtle">
                    Query: {request.query_text}
                  </div>
                )}
              </div>
            </div>

            {request.cached_answer && (
              <div className="bg-background p-4 rounded border border-border">
                <div className="text-sm whitespace-pre-wrap leading-relaxed">
                  {request.cached_answer}
                </div>
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Pending Requests */}
      {pendingRequests.map((request) => (
        <div
          key={request.id}
          className="bg-warning/5 border border-warning/30 rounded-lg px-4 py-3"
        >
          <div className="flex items-center gap-3">
            <Clock className="h-5 w-5 text-warning" />
            <div>
              <div className="text-sm font-medium">
                Awaiting approval from {request.avatar_user_email}
              </div>
              {request.query_text && (
                <div className="text-xs text-text-subtle truncate max-w-md">
                  Query: {request.query_text}
                </div>
              )}
              <div className="text-xs text-warning mt-1">
                You'll see the answer here once approved
              </div>
            </div>
          </div>
        </div>
      ))}

      {/* Denied Requests */}
      {deniedRequests.map((request) => (
        <div
          key={request.id}
          className="bg-error/5 border border-error/30 rounded-lg px-4 py-3"
        >
          <div className="flex items-center gap-3">
            <XCircle className="h-5 w-5 text-error" />
            <div>
              <div className="text-sm font-medium">
                Request denied by {request.avatar_user_email}
              </div>
              {request.denial_reason && (
                <div className="text-xs text-error mt-1">
                  Reason: {request.denial_reason}
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default ChatSessionAvatarRequests;

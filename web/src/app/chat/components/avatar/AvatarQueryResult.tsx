"use client";

import React from "react";
import Link from "next/link";
import { useAvatarContextOptional } from "@/app/chat/avatars/AvatarContext";
import { AvatarQueryResponse } from "@/lib/types";
import {
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  FileText,
  X,
  Loader2,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";

export function AvatarQueryResult() {
  const avatarContext = useAvatarContextOptional();

  if (!avatarContext) {
    return null;
  }

  const { isQuerying, lastResult, queryError, clearResult, selectedAvatar } =
    avatarContext;

  // Show loading state
  if (isQuerying) {
    return (
      <div className="w-full max-w-[50rem] mb-4">
        <div className="bg-background-subtle border border-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-accent" />
            <div>
              <div className="text-sm font-medium">Querying avatar...</div>
              <div className="text-xs text-text-subtle">
                Searching {selectedAvatar?.name || selectedAvatar?.user_email}'s
                knowledge
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Show error state
  if (queryError) {
    return (
      <div className="w-full max-w-[50rem] mb-4">
        <div className="bg-error/10 border border-error rounded-lg p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <XCircle className="h-5 w-5 text-error flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-sm font-medium text-error">
                  Query Failed
                </div>
                <div className="text-xs text-error/80 mt-1">{queryError}</div>
              </div>
            </div>
            <button
              onClick={clearResult}
              className="p-1 hover:bg-error/10 rounded transition-colors"
            >
              <X className="h-4 w-4 text-error" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Show result
  if (!lastResult) {
    return null;
  }

  return (
    <div className="w-full max-w-[50rem] mb-4">
      <QueryResultCard result={lastResult} onClose={clearResult} />
    </div>
  );
}

interface QueryResultCardProps {
  result: AvatarQueryResponse;
  onClose: () => void;
}

function QueryResultCard({ result, onClose }: QueryResultCardProps) {
  const getStatusDisplay = () => {
    switch (result.status) {
      case "success":
        return {
          icon: <CheckCircle className="h-5 w-5 text-success" />,
          title: "Query Successful",
          bgColor: "bg-success/10",
          borderColor: "border-success/30",
        };
      case "pending_permission":
        return {
          icon: <Clock className="h-5 w-5 text-warning" />,
          title: "Permission Required",
          bgColor: "bg-warning/10",
          borderColor: "border-warning/30",
        };
      case "no_results":
        return {
          icon: <FileText className="h-5 w-5 text-text-subtle" />,
          title: "No Results",
          bgColor: "bg-background-subtle",
          borderColor: "border-border",
        };
      case "rate_limited":
        return {
          icon: <AlertCircle className="h-5 w-5 text-warning" />,
          title: "Rate Limited",
          bgColor: "bg-warning/10",
          borderColor: "border-warning/30",
        };
      case "disabled":
        return {
          icon: <XCircle className="h-5 w-5 text-error" />,
          title: "Avatar Disabled",
          bgColor: "bg-error/10",
          borderColor: "border-error/30",
        };
      case "error":
      default:
        return {
          icon: <XCircle className="h-5 w-5 text-error" />,
          title: "Error",
          bgColor: "bg-error/10",
          borderColor: "border-error/30",
        };
    }
  };

  const status = getStatusDisplay();

  return (
    <div
      className={cn(
        status.bgColor,
        "border",
        status.borderColor,
        "rounded-lg p-4"
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          {status.icon}
          <h4 className="font-semibold text-sm">{status.title}</h4>
        </div>
        <button
          onClick={onClose}
          className="p-1 hover:bg-background rounded transition-colors"
        >
          <X className="h-4 w-4 text-text-subtle" />
        </button>
      </div>

      {result.message && (
        <p className="text-sm text-text-subtle mb-3">{result.message}</p>
      )}

      {result.answer && (
        <div className="bg-background p-4 rounded border border-border">
          <h5 className="text-xs font-medium text-text-subtle mb-2">Answer</h5>
          <div className="text-sm whitespace-pre-wrap">{result.answer}</div>
        </div>
      )}

      {result.source_document_ids && result.source_document_ids.length > 0 && (
        <div className="mt-3">
          <h5 className="text-xs font-medium text-text-subtle mb-2">Sources</h5>
          <div className="flex flex-wrap gap-2">
            {result.source_document_ids.slice(0, 5).map((docId, idx) => (
              <span
                key={idx}
                className="text-xs bg-background px-2 py-1 rounded border border-border"
              >
                {docId.length > 20 ? `${docId.slice(0, 20)}...` : docId}
              </span>
            ))}
            {result.source_document_ids.length > 5 && (
              <span className="text-xs text-text-subtle">
                +{result.source_document_ids.length - 5} more
              </span>
            )}
          </div>
        </div>
      )}

      {result.permission_request_id && (
        <div className="mt-3 p-3 bg-background rounded border border-border">
          <p className="text-sm">
            Your request has been sent! Request ID:{" "}
            <code className="bg-background-subtle px-1 rounded text-xs">
              #{result.permission_request_id}
            </code>
          </p>
          <p className="text-xs text-text-subtle mt-1">
            You'll be notified when the avatar owner responds.
          </p>
          <Link
            href="/avatars?tab=requests"
            className="inline-flex items-center gap-1 mt-2 text-xs text-accent hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            View My Requests
          </Link>
        </div>
      )}
    </div>
  );
}

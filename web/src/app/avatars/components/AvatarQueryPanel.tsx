"use client";

import React, { useState } from "react";
import {
  AvatarListItem,
  AvatarQueryMode,
  AvatarQueryResponse,
} from "@/lib/types";
import { useAvatarQuery } from "@/lib/avatar";
import { AvatarSelector } from "./AvatarSelector";
import {
  Search,
  Send,
  Loader2,
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  FileText,
} from "lucide-react";

export function AvatarQueryPanel() {
  const [selectedAvatar, setSelectedAvatar] = useState<AvatarListItem | null>(
    null
  );
  const [queryText, setQueryText] = useState("");
  const [queryMode, setQueryMode] = useState<AvatarQueryMode>(
    AvatarQueryMode.OWNED_DOCUMENTS
  );

  const { query, loading, error, result, clearResult } = useAvatarQuery();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAvatar || !queryText.trim()) return;

    try {
      await query(selectedAvatar.id, queryText.trim(), queryMode);
    } catch {
      // Error is handled by the hook
    }
  };

  const handleAvatarSelect = (avatar: AvatarListItem) => {
    setSelectedAvatar(avatar);
    clearResult();
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Avatar Selection */}
      <div className="bg-background-subtle p-4 rounded-lg">
        <h3 className="text-lg font-semibold mb-3">
          Select an Avatar to Query
        </h3>
        <AvatarSelector
          onSelect={handleAvatarSelect}
          selectedAvatarId={selectedAvatar?.id}
        />
      </div>

      {/* Query Form */}
      {selectedAvatar && (
        <div className="bg-background-subtle p-4 rounded-lg">
          <h3 className="text-lg font-semibold mb-3">
            Query {selectedAvatar.name || selectedAvatar.user_email}'s Knowledge
          </h3>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Query Mode Selection */}
            <div>
              <label className="block text-sm font-medium mb-2">
                Query Mode
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="queryMode"
                    checked={queryMode === AvatarQueryMode.OWNED_DOCUMENTS}
                    onChange={() =>
                      setQueryMode(AvatarQueryMode.OWNED_DOCUMENTS)
                    }
                    className="text-accent"
                  />
                  <span className="text-sm">Owned Documents</span>
                  <span className="text-xs text-text-subtle">(Instant)</span>
                </label>
                {selectedAvatar.allow_accessible_mode && (
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="queryMode"
                      checked={
                        queryMode === AvatarQueryMode.ACCESSIBLE_DOCUMENTS
                      }
                      onChange={() =>
                        setQueryMode(AvatarQueryMode.ACCESSIBLE_DOCUMENTS)
                      }
                      className="text-accent"
                    />
                    <span className="text-sm">All Accessible</span>
                    <span className="text-xs text-text-subtle">
                      (Requires Permission)
                    </span>
                  </label>
                )}
              </div>
            </div>

            {/* Query Input */}
            <div>
              <label className="block text-sm font-medium mb-2">
                Your Question
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-3 h-5 w-5 text-text-subtle" />
                <textarea
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder="What would you like to know from this person's knowledge?"
                  className="w-full pl-10 pr-3 py-2 border border-border rounded-lg bg-background min-h-[100px] resize-y focus:outline-none focus:ring-2 focus:ring-accent"
                  disabled={loading}
                />
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading || !queryText.trim()}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Querying...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  Send Query
                </>
              )}
            </button>
          </form>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="bg-error/10 border border-error text-error p-4 rounded-lg flex items-center gap-2">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Result Display */}
      {result && <QueryResultDisplay result={result} />}
    </div>
  );
}

interface QueryResultDisplayProps {
  result: AvatarQueryResponse;
}

function QueryResultDisplay({ result }: QueryResultDisplayProps) {
  const getStatusDisplay = () => {
    switch (result.status) {
      case "success":
        return {
          icon: <CheckCircle className="h-5 w-5 text-success" />,
          title: "Query Successful",
          bgColor: "bg-success/10",
          borderColor: "border-success",
        };
      case "pending_permission":
        return {
          icon: <Clock className="h-5 w-5 text-warning" />,
          title: "Permission Required",
          bgColor: "bg-warning/10",
          borderColor: "border-warning",
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
          borderColor: "border-warning",
        };
      case "disabled":
        return {
          icon: <XCircle className="h-5 w-5 text-error" />,
          title: "Avatar Disabled",
          bgColor: "bg-error/10",
          borderColor: "border-error",
        };
      case "error":
      default:
        return {
          icon: <XCircle className="h-5 w-5 text-error" />,
          title: "Error",
          bgColor: "bg-error/10",
          borderColor: "border-error",
        };
    }
  };

  const status = getStatusDisplay();

  return (
    <div
      className={`${status.bgColor} border ${status.borderColor} p-4 rounded-lg`}
    >
      <div className="flex items-center gap-2 mb-3">
        {status.icon}
        <h4 className="font-semibold">{status.title}</h4>
      </div>

      {result.message && (
        <p className="text-sm text-text-subtle mb-3">{result.message}</p>
      )}

      {result.answer && (
        <div className="bg-background p-4 rounded border border-border">
          <h5 className="text-sm font-medium mb-2">Answer</h5>
          <div className="text-sm whitespace-pre-wrap">{result.answer}</div>
        </div>
      )}

      {result.source_document_ids && result.source_document_ids.length > 0 && (
        <div className="mt-3">
          <h5 className="text-sm font-medium mb-2">Sources</h5>
          <div className="flex flex-wrap gap-2">
            {result.source_document_ids.slice(0, 5).map((docId, idx) => (
              <span
                key={idx}
                className="text-xs bg-background px-2 py-1 rounded border border-border"
              >
                {docId.slice(0, 20)}...
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
            <code className="bg-background-subtle px-1 rounded">
              #{result.permission_request_id}
            </code>
          </p>
          <p className="text-xs text-text-subtle mt-1">
            You'll be notified when the avatar owner responds.
          </p>
        </div>
      )}
    </div>
  );
}

export default AvatarQueryPanel;

"use client";

import { useEffect, useState } from "react";
import SvgTrash from "@/icons/trash";
import SvgCopy from "@/icons/copy";
import SvgCheck from "@/icons/check";
import SvgPlusCircle from "@/icons/plus-circle";

import { usePopup } from "@/components/admin/connectors/Popup";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Utility: Format date consistently (UTC -> local)
function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

export function PATManagement() {
  const [pats, setPats] = useState<PAT[]>([]);
  const [isCreating, setIsCreating] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const { setPopup } = usePopup();

  const fetchPATs = async () => {
    try {
      const response = await fetch("/api/user/tokens");
      if (response.ok) {
        const data = await response.json();
        setPats(data);
      } else {
        setPopup({ message: "Failed to load tokens", type: "error" });
      }
    } catch (error) {
      setPopup({ message: "Network error loading tokens", type: "error" });
    } finally {
      setIsLoading(false);
    }
  };

  const createPAT = async () => {
    if (!newTokenName.trim()) {
      setPopup({ message: "Token name is required", type: "error" });
      return;
    }

    setIsCreating(true);
    try {
      const response = await fetch("/api/user/tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newTokenName,
          expiration_days:
            expirationDays === "null" ? null : parseInt(expirationDays),
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setCreatedToken(data.token);
        setNewTokenName("");
        setExpirationDays("30");
        setPopup({ message: "Token created successfully", type: "success" });
        await fetchPATs();
      } else {
        const error = await response.json();
        setPopup({
          message: error.detail || "Failed to create token",
          type: "error",
        });
      }
    } catch (error) {
      setPopup({ message: "Network error creating token", type: "error" });
    } finally {
      setIsCreating(false);
    }
  };

  const deletePAT = async (patId: number, patName: string) => {
    if (!confirm(`Are you sure you want to delete token "${patName}"?`)) {
      return;
    }

    try {
      const response = await fetch(`/api/user/tokens/${patId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        await fetchPATs();
        setPopup({ message: "Token deleted successfully", type: "success" });
      } else {
        setPopup({ message: "Failed to delete token", type: "error" });
      }
    } catch (error) {
      setPopup({ message: "Network error deleting token", type: "error" });
    }
  };

  const copyToken = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedToken(true);
      setPopup({ message: "Copied to clipboard", type: "success" });
      setTimeout(() => setCopiedToken(false), 2000);
    } catch (error) {
      setPopup({ message: "Failed to copy token", type: "error" });
    }
  };

  useEffect(() => {
    fetchPATs();
  }, []);

  // Show create form by default if no tokens exist
  useEffect(() => {
    if (!isLoading && pats.length === 0 && !createdToken) {
      setShowCreateForm(true);
    }
  }, [isLoading, pats.length, createdToken]);

  return (
    <div className="space-y-6">
      {/* Loading State */}
      {isLoading && (
        <Text text03 secondaryBody>
          Loading tokens...
        </Text>
      )}

      {/* Token Creation Success Modal */}
      {!isLoading && createdToken && (
        <div
          role="dialog"
          aria-labelledby="token-modal-title"
          aria-modal="true"
          className="p-4 bg-background-emphasis border border-border-strong rounded-lg"
        >
          <Text id="token-modal-title" headingH3 text01 className="mb-2">
            Token Created!
          </Text>
          <Text text02 secondaryBody className="mb-3">
            Copy this token now. You won&apos;t be able to see it again.
          </Text>
          <code className="block p-3 bg-background-02 border border-border-01 rounded text-xs break-all font-mono text-text-01">
            {createdToken}
          </code>
          <div className="flex gap-2 mt-3">
            <Button
              onClick={() => copyToken(createdToken)}
              primary
              leftIcon={copiedToken ? SvgCheck : SvgCopy}
              aria-label="Copy token to clipboard"
            >
              {copiedToken ? "Copied!" : "Copy Token"}
            </Button>
            <Button
              onClick={() => setCreatedToken(null)}
              secondary
              aria-label="Close token display"
            >
              Close
            </Button>
          </div>
        </div>
      )}

      {/* Create New Token Form */}
      {!isLoading && showCreateForm && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Text headingH3 text01>
              {pats.length === 0
                ? "Create Your First Token"
                : "Create New Token"}
            </Text>
            {pats.length > 0 && (
              <Button
                onClick={() => setShowCreateForm(false)}
                internal
                aria-label="Cancel token creation"
              >
                Cancel
              </Button>
            )}
          </div>
          <div className="space-y-3">
            <InputTypeIn
              placeholder="Token name (e.g., 'MCP Client')"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              disabled={isCreating}
              aria-label="Token name"
            />
            <div className="space-y-1">
              {/* NOTE: Use Select dropdown (not free text input) to guide users to common values.
                  Backend accepts any positive integer, but we provide curated options for UX. */}
              <Select
                value={expirationDays}
                onValueChange={setExpirationDays}
                disabled={isCreating}
              >
                <SelectTrigger aria-label="Select token expiration">
                  <SelectValue placeholder="Select expiration" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="7">7 days</SelectItem>
                  <SelectItem value="30">30 days</SelectItem>
                  <SelectItem value="365">365 days</SelectItem>
                  <SelectItem value="null">No expiration</SelectItem>
                </SelectContent>
              </Select>
              <Text text02 secondaryBody>
                Expires at end of day (23:59 UTC).
              </Text>
            </div>
            <Button onClick={createPAT} disabled={isCreating} primary>
              {isCreating ? "Creating..." : "Create Token"}
            </Button>
          </div>
        </div>
      )}

      {/* Token List */}
      {!isLoading && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Text headingH3 text01>
              Your Tokens
            </Text>
            {pats.length > 0 && !showCreateForm && (
              <Button
                onClick={() => setShowCreateForm(true)}
                primary
                leftIcon={SvgPlusCircle}
                aria-label="Create new token"
              >
                New Token
              </Button>
            )}
          </div>
          {pats.length === 0 ? (
            <div className="text-center py-8 px-4 border-2 border-dashed border-border-01 rounded-lg">
              <Text text03 secondaryBody className="mb-4">
                No tokens created yet. Create your first token to get started.
              </Text>
              {!showCreateForm && (
                <Button
                  onClick={() => setShowCreateForm(true)}
                  primary
                  leftIcon={SvgPlusCircle}
                  aria-label="Create your first token"
                >
                  Create Your First Token
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {pats.map((pat) => (
                <div
                  key={pat.id}
                  className="flex items-center justify-between p-3 border border-border-01 rounded-lg bg-background-tint-01"
                >
                  <div className="flex-1 min-w-0">
                    <Text text01 mainUiAction className="truncate">
                      {pat.name}
                    </Text>
                    <Text text03 secondaryMono>
                      {pat.token_display}
                    </Text>
                    <Text text03 secondaryBody className="mt-1">
                      <span title={formatDateTime(pat.created_at)}>
                        Created: {formatDate(pat.created_at)}
                      </span>
                      {pat.expires_at && (
                        <span title={formatDateTime(pat.expires_at)}>
                          {" • Expires: "}
                          {formatDate(pat.expires_at)}
                        </span>
                      )}
                      {pat.last_used_at && (
                        <span title={formatDateTime(pat.last_used_at)}>
                          {" • Last used: "}
                          {formatDate(pat.last_used_at)}
                        </span>
                      )}
                    </Text>
                  </div>
                  <Button
                    onClick={() => deletePAT(pat.id, pat.name)}
                    internal
                    leftIcon={SvgTrash}
                    className="ml-2"
                    data-testid={`delete-pat-${pat.id}`}
                    aria-label={`Delete token ${pat.name}`}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

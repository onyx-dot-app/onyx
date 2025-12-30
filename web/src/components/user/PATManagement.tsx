"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { usePopup } from "@/components/admin/connectors/Popup";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { humanReadableFormat, humanReadableFormatWithTime } from "@/lib/time";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { SvgCheck, SvgCopy, SvgTrash } from "@opal/icons";

interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

interface CreatedTokenState {
  id: number;
  token: string;
}

export default function PATManagement() {
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [newlyCreatedToken, setNewlyCreatedToken] =
    useState<CreatedTokenState | null>(null);
  const [copiedTokenId, setCopiedTokenId] = useState<number | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const { setPopup } = usePopup();

  // Use SWR for token fetching with caching
  const {
    data: pats = [],
    mutate,
    error,
    isLoading,
  } = useSWR<PAT[]>("/api/user/pats", errorHandlingFetcher, {
    revalidateOnFocus: true,
    dedupingInterval: 2000,
    fallbackData: [],
  });

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      setPopup({ message: "Failed to load tokens", type: "error" });
    }
  }, [error, setPopup]);

  const createPAT = async () => {
    if (!newTokenName.trim()) {
      setPopup({ message: "Token name is required", type: "error" });
      return;
    }

    setIsCreating(true);
    try {
      const response = await fetch("/api/user/pats", {
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
        // Store the newly created token with its ID and full token value
        setNewlyCreatedToken({ id: data.id, token: data.token });
        setNewTokenName("");
        setExpirationDays("30");
        setPopup({ message: "Token created successfully", type: "success" });
        // Revalidate the token list
        await mutate();
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

  const deletePAT = async (patId: number) => {
    try {
      const response = await fetch(`/api/user/pats/${patId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        // Clear the newly created token if it's the one being deleted
        if (newlyCreatedToken?.id === patId) {
          setNewlyCreatedToken(null);
        }
        await mutate();
        setPopup({ message: "Token deleted successfully", type: "success" });
      } else {
        setPopup({ message: "Failed to delete token", type: "error" });
      }
    } catch (error) {
      setPopup({ message: "Network error deleting token", type: "error" });
    } finally {
      setTokenToDelete(null);
    }
  };

  const copyToken = async (token: string, tokenId: number) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedTokenId(tokenId);
      setPopup({ message: "Copied to clipboard", type: "success" });
      setTimeout(() => setCopiedTokenId(null), 2000);
    } catch (error) {
      setPopup({ message: "Failed to copy token", type: "error" });
    }
  };

  return (
    <>
      {tokenToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Token"
          onClose={() => setTokenToDelete(null)}
          submit={
            <Button danger onClick={() => deletePAT(tokenToDelete.id)}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete token &quot;{tokenToDelete.name}
          &quot;? This action cannot be undone.
        </ConfirmationModalLayout>
      )}

      <div className="space-y-6">
        {/* Create New Token Form */}
        <div className="space-y-4">
          <Text as="p" headingH3Muted>
            Create New Token
          </Text>
          <div className="space-y-3">
            <InputTypeIn
              placeholder="Token name (e.g., 'MCP Client')"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              disabled={isCreating}
              aria-label="Token name"
              autoComplete="new-password"
            />
            {/* autoComplete="new-password" is a workaround for Safari browers to disable autoComplete*/}
            <div className="space-y-1" aria-label="Select token expiration">
              {/* NOTE: Use Select dropdown (not free text input) to guide users to common values.
                  Backend accepts any positive integer, but we provide curated options for UX. */}
              <InputSelect
                value={expirationDays}
                onValueChange={setExpirationDays}
                disabled={isCreating}
              >
                <InputSelect.Trigger placeholder="Select expiration" />
                <InputSelect.Content>
                  <InputSelect.Item value="7">7 days</InputSelect.Item>
                  <InputSelect.Item value="30">30 days</InputSelect.Item>
                  <InputSelect.Item value="365">365 days</InputSelect.Item>
                  <InputSelect.Item value="null">
                    No expiration
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>

              <Text as="p" text02 secondaryBody>
                Expires at end of day (23:59 UTC).
              </Text>
            </div>
            <Button
              onClick={createPAT}
              disabled={isCreating || !newTokenName.trim()}
              primary
            >
              {isCreating ? "Creating..." : "Create Token"}
            </Button>
          </div>
        </div>

        {/* Token List */}
        <div className="space-y-4">
          <Text as="p" headingH3Muted>
            Your Tokens
          </Text>
          {pats.length === 0 ? (
            <div className="text-center py-8 px-4 border-2 border-dashed border-border-01 rounded-lg">
              <Text as="p" text03 secondaryBody>
                {isLoading
                  ? "Loading tokens..."
                  : "No tokens created yet. Create your first token above."}
              </Text>
            </div>
          ) : (
            <div className="space-y-2">
              {pats.map((pat) => {
                const isNewlyCreated = newlyCreatedToken?.id === pat.id;
                const isCopied = copiedTokenId === pat.id;

                return (
                  <div
                    key={pat.id}
                    className={`flex items-center justify-between p-3 border rounded-lg ${
                      isNewlyCreated
                        ? "bg-accent-emphasis border-accent-strong"
                        : "border-border-01 bg-background-tint-01"
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <Text as="p" text05 mainUiAction className="truncate">
                        {pat.name}
                      </Text>
                      {isNewlyCreated ? (
                        <>
                          <Text as="p" text05 secondaryBody className="mb-2">
                            Copy this token now. You won&apos;t be able to see
                            it again.
                          </Text>
                          <code className="block p-2 bg-background-02 border border-border-01 rounded text-xs break-all font-mono text-text-01 mb-2">
                            {newlyCreatedToken.token}
                          </code>
                          <Button
                            onClick={() =>
                              copyToken(newlyCreatedToken.token, pat.id)
                            }
                            primary
                            leftIcon={isCopied ? SvgCheck : SvgCopy}
                            aria-label="Copy token to clipboard"
                          >
                            {isCopied ? "Copied!" : "Copy Token"}
                          </Button>
                        </>
                      ) : (
                        <Text as="p" text03 secondaryMono>
                          {pat.token_display}
                        </Text>
                      )}
                      <Text as="p" text03 secondaryBody className="mt-1">
                        <span
                          title={humanReadableFormatWithTime(pat.created_at)}
                        >
                          Created: {humanReadableFormat(pat.created_at)}
                        </span>
                        {pat.expires_at && (
                          <span
                            title={humanReadableFormatWithTime(pat.expires_at)}
                          >
                            {" • Expires: "}
                            {humanReadableFormat(pat.expires_at)}
                          </span>
                        )}
                        {pat.last_used_at && (
                          <span
                            title={humanReadableFormatWithTime(
                              pat.last_used_at
                            )}
                          >
                            {" • Last used: "}
                            {humanReadableFormat(pat.last_used_at)}
                          </span>
                        )}
                      </Text>
                    </div>
                    <IconButton
                      icon={SvgTrash}
                      onClick={() =>
                        setTokenToDelete({ id: pat.id, name: pat.name })
                      }
                      internal
                      data-testid={`delete-pat-${pat.id}`}
                      aria-label={`Delete token ${pat.name}`}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

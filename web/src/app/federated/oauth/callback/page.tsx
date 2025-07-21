"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckmarkIcon, TriangleAlertIcon } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";
import { getSourceDisplayName } from "@/lib/sources";

export default function FederatedOAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState("Processing...");
  const [statusDetails, setStatusDetails] = useState(
    "Please wait while we complete the setup."
  );
  const [isError, setIsError] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Extract query parameters
  const code = searchParams?.get("code");
  const state = searchParams?.get("state");
  const error = searchParams?.get("error");
  const errorDescription = searchParams?.get("error_description");

  // Auto-redirect for success cases
  useEffect(() => {
    if (isSuccess) {
      const timer = setTimeout(() => {
        router.push("/chat");
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isSuccess, router]);

  useEffect(() => {
    const handleOAuthCallback = async () => {
      // Handle OAuth error from provider
      if (error) {
        setStatusMessage("Authorization Failed");
        setStatusDetails(
          errorDescription ||
            "The authorization was cancelled or failed. Please try again."
        );
        setIsError(true);
        setIsLoading(false);
        return;
      }

      // Validate required parameters
      if (!code || !state) {
        setStatusMessage("Invalid Request");
        setStatusDetails(
          "The authorization request was incomplete. Please try again."
        );
        setIsError(true);
        setIsLoading(false);
        return;
      }

      try {
        // Use the generic callback endpoint
        const url = `/api/federated/callback?code=${encodeURIComponent(
          code
        )}&state=${encodeURIComponent(state)}`;

        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (!response.ok) {
          let errorMessage = "Failed to complete authorization";
          try {
            const errorData = await response.json();
            if (errorData.detail) {
              // Clean up technical error messages for user-friendly display
              if (errorData.detail.includes("validation errors")) {
                errorMessage =
                  "Configuration error - please check your connector settings";
              } else if (errorData.detail.includes("client_secret")) {
                errorMessage =
                  "Authentication credentials are missing or invalid";
              } else if (errorData.detail.includes("oauth")) {
                errorMessage = "OAuth authorization failed";
              } else {
                errorMessage = "Authorization failed - please try again";
              }
            }
          } catch (parseError) {
            console.error("Error parsing response:", parseError);
          }
          throw new Error(errorMessage);
        }

        // Parse the response to get source information
        const responseData = await response.json();
        const source = responseData.source;
        const displayName = source ? getSourceDisplayName(source) : "connector";

        setStatusMessage("Success!");
        setStatusDetails(
          `Your ${displayName} authorization completed successfully. You can now use this connector for search.`
        );
        setIsSuccess(true);
        setIsError(false);
        setIsLoading(false);
      } catch (error) {
        console.error("Federated OAuth callback error:", error);
        setStatusMessage("Something Went Wrong");
        setStatusDetails(
          error instanceof Error
            ? error.message
            : "An error occurred during the OAuth process. Please try again."
        );
        setIsError(true);
        setIsLoading(false);
      }
    };

    handleOAuthCallback();
  }, [code, state, error, errorDescription]);

  const getStatusIcon = () => {
    if (isLoading) {
      return (
        <div className="w-16 h-16 border-4 border-blue-200 dark:border-blue-800 border-t-blue-600 dark:border-t-blue-400 rounded-full animate-spin mx-auto mb-4"></div>
      );
    }
    if (isSuccess) {
      return (
        <CheckmarkIcon
          size={64}
          className="text-green-500 dark:text-green-400 mx-auto mb-4"
        />
      );
    }
    if (isError) {
      return (
        <TriangleAlertIcon
          size={64}
          className="text-red-500 dark:text-red-400 mx-auto mb-4"
        />
      );
    }
    return null;
  };

  const getStatusColor = () => {
    if (isSuccess) return "text-green-600 dark:text-green-400";
    if (isError) return "text-red-600 dark:text-red-400";
    return "text-gray-600 dark:text-gray-300";
  };

  return (
    <div className="min-h-screen flex flex-col">
      <div className="flex-1 flex flex-col items-center justify-center p-4">
        <CardSection className="max-w-md w-full mx-auto p-8 shadow-lg bg-white dark:bg-gray-800 rounded-lg">
          <div className="text-center">
            {getStatusIcon()}

            <h1 className={`text-2xl font-bold mb-4 ${getStatusColor()}`}>
              {statusMessage}
            </h1>

            <p className="text-gray-600 dark:text-gray-300 mb-6 leading-relaxed">
              {statusDetails}
            </p>

            {isSuccess && (
              <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6">
                <p className="text-green-800 dark:text-green-200 text-sm">
                  Redirecting to chat in 2 seconds...
                </p>
              </div>
            )}

            <div className="flex flex-col space-y-3">
              {isError && (
                <div className="flex flex-col space-y-2">
                  <Button
                    onClick={() => router.push("/chat")}
                    variant="navigate"
                    className="w-full"
                  >
                    Back to Chat
                  </Button>
                </div>
              )}

              {isLoading && (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  This may take a few moments...
                </p>
              )}
            </div>
          </div>
        </CardSection>
      </div>
    </div>
  );
}

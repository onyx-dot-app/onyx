"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckmarkIcon, TriangleAlertIcon } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@/components/ui/button";

interface OAuthCallbackConfig {
  // UI customization
  processingMessage?: string;
  processingDetails?: string;
  successMessage?: string;
  successDetailsTemplate?: string; // Template with {serviceName} placeholder
  errorMessage?: string;
  backButtonText?: string;
  redirectingMessage?: string;

  // Behavior
  autoRedirectDelay?: number; // milliseconds
  defaultRedirectPath?: string;

  // API integration - all flows now use the same pattern
  callbackApiUrl: string; // Required - API endpoint to call

  // Error message mapping
  errorMessageMap?: Record<string, string>;
}

interface OAuthCallbackPageProps {
  config: OAuthCallbackConfig;
}

export default function OAuthCallbackPage({ config }: OAuthCallbackPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState(
    config.processingMessage || "Processing..."
  );
  const [statusDetails, setStatusDetails] = useState(
    config.processingDetails || "Please wait while we complete the setup."
  );
  const [isError, setIsError] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [serviceName, setServiceName] = useState<string>("");
  const [redirectPath, setRedirectPath] = useState<string | undefined>(
    undefined
  );
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  // Extract query parameters
  const code = searchParams?.get("code");
  const state = searchParams?.get("state");
  const error = searchParams?.get("error");
  const errorDescription = searchParams?.get("error_description");

  // Auto-redirect for success cases (with countdown)
  useEffect(() => {
    if (!isSuccess) return;

    const delayMs = config.autoRedirectDelay ?? 2000;
    setSecondsLeft(Math.ceil(delayMs / 1000));

    const interval = setInterval(() => {
      setSecondsLeft((prev) => (prev !== null && prev > 0 ? prev - 1 : prev));
    }, 1000);

    const timer = setTimeout(() => {
      const target = redirectPath || config.defaultRedirectPath || "/chat";
      router.push(target);
    }, delayMs);

    return () => {
      clearInterval(interval);
      clearTimeout(timer);
    };
  }, [
    isSuccess,
    redirectPath,
    router,
    config.autoRedirectDelay,
    config.defaultRedirectPath,
  ]);

  useEffect(() => {
    const handleOAuthCallback = async () => {
      // Handle OAuth error from provider
      if (error) {
        setStatusMessage(config.errorMessage || "Authorization Failed");
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
        // Make API call to process callback - all flows use this pattern now
        const url = `${config.callbackApiUrl}?code=${encodeURIComponent(
          code
        )}&state=${encodeURIComponent(state)}`;

        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
        });

        if (!response.ok) {
          let errorMessage = "Failed to complete authorization";
          try {
            const errorData = await response.json();
            if (errorData.detail && config.errorMessageMap) {
              // Use custom error mapping
              for (const [pattern, message] of Object.entries(
                config.errorMessageMap
              )) {
                if (errorData.detail.includes(pattern)) {
                  errorMessage = message;
                  break;
                }
              }
            } else if (errorData.error) {
              errorMessage = errorData.error;
            }
          } catch (parseError) {
            console.error("Error parsing response:", parseError);
          }
          throw new Error(errorMessage);
        }

        // Parse the response to get service and redirect information
        const responseData = await response.json();
        const result = {
          success: true,
          serviceName:
            responseData.source ||
            responseData.server_name ||
            responseData.service_name,
        };

        setServiceName(result.serviceName || "");
        // Respect backend-provided redirect path (from state.return_path)
        setRedirectPath(
          responseData.redirect_url ||
            searchParams?.get("return_path") ||
            config.defaultRedirectPath ||
            "/chat"
        );
        setStatusMessage(config.successMessage || "Success!");

        const successDetails = config.successDetailsTemplate
          ? config.successDetailsTemplate.replace(
              "{serviceName}",
              result.serviceName || "service"
            )
          : `Your ${
              result.serviceName || "service"
            } authorization completed successfully.`;

        setStatusDetails(successDetails);
        setIsSuccess(true);
        setIsError(false);
        setIsLoading(false);
      } catch (error) {
        console.error("OAuth callback error:", error);
        setStatusMessage(config.errorMessage || "Something Went Wrong");
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
  }, [code, state, error, errorDescription, searchParams, config]);

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

            {isSuccess && secondsLeft !== null && (
              <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6">
                <p className="text-green-800 dark:text-green-200 text-sm">
                  Redirecting in {secondsLeft}{" "}
                  {secondsLeft === 1 ? "second" : "seconds"}...
                </p>
              </div>
            )}

            <div className="flex flex-col space-y-3">
              {isError && (
                <div className="flex flex-col space-y-2">
                  <Button
                    onClick={() => {
                      const target =
                        redirectPath || config.defaultRedirectPath || "/chat";
                      router.push(target);
                    }}
                    variant="navigate"
                    className="w-full"
                  >
                    {config.backButtonText || "Back to Chat"}
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

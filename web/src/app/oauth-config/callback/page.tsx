import OAuthCallbackPage from "@/components/oauth/OAuthCallbackPage";

export default function OAuthConfigCallbackPage() {
  return (
    <OAuthCallbackPage
      config={{
        callbackApiUrl: "/api/oauth-config/callback",
        defaultRedirectPath: "/chat",
        processingMessage: "Completing Authorization...",
        processingDetails:
          "Please wait while we securely store your credentials.",
        successMessage: "Authorization Successful!",
        successDetailsTemplate:
          "You have successfully authorized the tool to access your {serviceName} account.",
        errorMessage: "Authorization Failed",
        backButtonText: "Back to Chat",
        autoRedirectDelay: 2000,
      }}
    />
  );
}

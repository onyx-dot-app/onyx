"use client";

import OAuthCallbackPage from "@/components/oauth/OAuthCallbackPage";

export default function MCPOAuthCallbackPage() {
  const mcpConfig = {
    processingMessage: "Processing...",
    processingDetails: "Please wait while we complete the MCP server setup.",
    successMessage: "Success!",
    successDetailsTemplate:
      "Your {serviceName} authorization completed successfully. You can now use this server's tools in chat.",
    errorMessage: "Something Went Wrong",
    backButtonText: "Back to Chat",
    redirectingMessage: "Redirecting back in 2 seconds...",
    autoRedirectDelay: 2000,
    defaultRedirectPath: "/chat",
    callbackApiUrl: "/api/mcp/oauth/callback",
    errorMessageMap: {
      "server not found": "MCP server configuration not found",
      credentials: "Authentication credentials are invalid",
      oauth: "OAuth authorization failed",
      validation: "Could not validate connection to MCP server",
    },
  };

  return <OAuthCallbackPage config={mcpConfig} />;
}

import { FiInfo, FiPlus, FiX, FiKey } from "react-icons/fi";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEffect } from "react";

interface PerUserAuthTemplateConfigProps {
  values: any;
  setFieldValue: (field: string, value: any) => void;
  errors: any;
  touched: any;
}

export function PerUserAuthTemplateConfig({
  values,
  setFieldValue,
  errors,
  touched,
}: PerUserAuthTemplateConfigProps) {
  useEffect(() => {
    // Initialize auth template if not exists
    if (!values.auth_template) {
      setFieldValue("auth_template", {
        headers: { Authorization: "Bearer {api_key}" },
        required_fields: ["api_key"],
      });
    }
  }, [values.auth_template, setFieldValue]);

  const addHeader = () => {
    const currentHeaders = values.auth_template?.headers || {};
    setFieldValue("auth_template.headers", {
      ...currentHeaders,
      [""]: "",
    });
  };

  const removeHeader = (name: string) => {
    const currentHeaders = values.auth_template?.headers || {};
    const { [name]: _, ...rest } = currentHeaders;
    setFieldValue("auth_template.headers", rest);
  };

  const updateHeader = (name: string, value: string) => {
    const currentHeaders = values.auth_template?.headers || {};
    const newHeaders = {
      ...currentHeaders,
      [name]: value,
    };
    setFieldValue("auth_template.headers", newHeaders);
    // Update required fields based on placeholders
    updateRequiredFields(newHeaders);
  };

  const renameHeader = (oldName: string, newName: string) => {
    if (oldName === newName) return;
    const currentHeaders: Record<string, string> =
      values.auth_template?.headers || {};
    // Preserve insertion order while renaming the key
    const newHeaders: Record<string, string> = {};
    for (const [k, v] of Object.entries(currentHeaders)) {
      if (k === oldName) {
        newHeaders[newName] = v ?? "";
      } else {
        newHeaders[k] = v;
      }
    }
    setFieldValue("auth_template.headers", newHeaders);
    updateRequiredFields(newHeaders);
  };

  const updateRequiredFields = (headers: Record<string, string>) => {
    const placeholderRegex = /\{([^}]+)\}/g;
    const requiredFields = new Set<string>();

    Object.values(headers).forEach((value) => {
      const matches = value.match(placeholderRegex);
      console.log(matches);
      if (matches) {
        matches.forEach((match: string) => {
          const field = match.slice(1, -1);
          if (field !== "user_email") {
            // user_email is automatically provided
            requiredFields.add(field);
          }
        });
      }
    });

    setFieldValue("auth_template.required_fields", Array.from(requiredFields));
  };

  const updateAdminCredential = (field: string, value: string) => {
    const currentCreds = values.user_credentials || {};
    setFieldValue("user_credentials", {
      ...currentCreds,
      [field]: value,
    });
  };

  const headers: Record<string, string> = values.auth_template?.headers || {};
  const requiredFields: string[] = values.auth_template?.required_fields || [];
  const adminCredentials = values.user_credentials || {};

  // Initialize required fields on component mount
  useEffect(() => {
    if (headers && Object.keys(headers).length > 0) {
      updateRequiredFields(headers);
    }
  }, []); // Empty dependency array - only run on mount

  return (
    <div className="space-y-4 p-4 bg-background-100 border border-border-strong rounded-lg">
      <div className="flex items-center space-x-2">
        <FiInfo className="h-4 w-4 text-text-700" />
        <h4 className="font-medium text-text-900">
          Per-User Authentication Template
        </h4>
      </div>

      <p className="text-sm text-text-800">
        Configure how users will authenticate with this MCP server. Define
        headers with placeholders that will be filled in by each user&apos;s
        credentials.
      </p>

      <div className="space-y-4">
        <div>
          <div className="flex items-center justify-between mb-2">
            <Label>Authentication Headers</Label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addHeader}
              className="flex items-center space-x-1"
            >
              <FiPlus className="h-3 w-3" />
              <span>Add Header</span>
            </Button>
          </div>

          <div className="space-y-2">
            {Object.entries(headers).map(([name, value], idx) => (
              <div key={idx} className="flex items-center space-x-2">
                <Input
                  placeholder="Header name (e.g., Authorization)"
                  value={name}
                  onChange={(e) => renameHeader(name, e.target.value)}
                  className="flex-1"
                />
                <Input
                  placeholder="Header value (e.g., Bearer {api_key})"
                  value={value}
                  onChange={(e) => updateHeader(name, e.target.value)}
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => removeHeader(name)}
                  className="text-red-600 hover:text-red-800"
                >
                  <FiX className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>

          <p className="text-xs text-text-600 mt-1">
            Use placeholders like{" "}
            <code className="bg-background-200 px-1 rounded">{`{api_key}`}</code>{" "}
            or{" "}
            <code className="bg-background-200 px-1 rounded">{`{user_email}`}</code>
            . Users will be prompted to provide values for placeholders (except
            user_email).
          </p>
        </div>

        {requiredFields.length > 0 && (
          <div>
            <Label>
              Your Credentials (for listing tools and saving your own access)
            </Label>
            <p className="text-xs text-text-600 mb-2">
              Provide values to validate the server configuration when listing
              tools. These will be saved as your per-user credentials if
              creation succeeds.
            </p>
            <div className="space-y-2">
              {requiredFields.map((field: string) => (
                <div key={field}>
                  <Label htmlFor={`test_${field}`} className="text-sm">
                    {field
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (l) => l.toUpperCase())}
                  </Label>
                  <Input
                    id={`test_${field}`}
                    type={
                      field.toLowerCase().includes("key") ||
                      field.toLowerCase().includes("token")
                        ? "password"
                        : "text"
                    }
                    placeholder={`Enter ${field.replace(/_/g, " ")}`}
                    value={adminCredentials[field] || ""}
                    onChange={(e) =>
                      updateAdminCredential(field, e.target.value)
                    }
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="text-xs text-text-600 space-y-1">
          <p>
            <strong>How it works:</strong>
          </p>
          <p>
            • Users will see a form asking for:{" "}
            {requiredFields.length > 0 ? requiredFields.join(", ") : "api_key"}
          </p>
          <p>
            • Their credentials will be validated against the server before
            being saved
          </p>
          <p>
            • Each user&apos;s credentials are stored securely and separately
          </p>
        </div>
      </div>
    </div>
  );
}

interface OAuthConfigProps {
  values: any;
  setFieldValue: (field: string, value: any) => void;
  errors: any;
  touched: any;
}

export function OAuthConfig({
  values,
  setFieldValue,
  errors,
  touched,
}: OAuthConfigProps) {
  const clientId = values.oauth_client_id || "";
  const clientSecret = values.oauth_client_secret || "";

  return (
    <div className="space-y-4 p-4 bg-background-100 border border-border-strong rounded-lg">
      <div className="flex items-center space-x-2">
        <FiKey className="h-4 w-4 text-text-700" />
        <h4 className="font-medium text-text-900">OAuth Configuration</h4>
      </div>

      <p className="text-sm text-text-800">
        Configure OAuth 2.0 credentials to authenticate with the MCP server.
        These credentials will be used to obtain access tokens.
      </p>

      <div className="space-y-4">
        <div>
          <Label htmlFor="oauth_client_id">Client ID (Optional)</Label>
          <Input
            id="oauth_client_id"
            type="text"
            placeholder="Enter your OAuth client ID"
            value={clientId}
            onChange={(e) => setFieldValue("oauth_client_id", e.target.value)}
            className="mt-1"
          />
          {errors.oauth_client_id && touched.oauth_client_id && (
            <div className="text-red-500 text-sm mt-1">
              {errors.oauth_client_id}
            </div>
          )}
        </div>

        <div>
          <Label htmlFor="oauth_client_secret">Client Secret (Optional)</Label>
          <Input
            id="oauth_client_secret"
            type="password"
            placeholder="Enter your OAuth client secret"
            value={clientSecret}
            onChange={(e) =>
              setFieldValue("oauth_client_secret", e.target.value)
            }
            className="mt-1"
          />
          {errors.oauth_client_secret && touched.oauth_client_secret && (
            <div className="text-red-500 text-sm mt-1">
              {errors.oauth_client_secret}
            </div>
          )}
        </div>

        <div className="text-xs text-text-600 space-y-1">
          <p>
            <strong>Note:</strong> Client ID and secret are optional if the MCP
            server supports Dynamic Client Registration (DCR). If DCR is not
            supported, you&apos;ll need to register your application with the
            MCP server provider to obtain these credentials.
          </p>
          <p>
            • The redirect URI should be set to:{" "}
            <code className="bg-background-200 px-1 rounded">
              {typeof window !== "undefined" ? window.location.origin : ""}
              /mcp/oauth/callback
            </code>
          </p>
          <p>
            • Make sure the OAuth app has the necessary scopes/permissions for
            the MCP server&apos;s operations
          </p>
        </div>
      </div>
    </div>
  );
}

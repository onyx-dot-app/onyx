"use client";

import { useEffect, useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import {
  Button,
  InputTypeIn,
  MessageCard,
  Tabs,
  Text,
  Tooltip,
} from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  CustomOAuthConfig,
  ExternalAppAdminResponse,
  TokenEndpointAuthMethod,
} from "@/app/craft/v1/apps/registry";
import {
  createCustomExternalApp,
  replaceCustomAppBundle,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";

type AuthMethod = "static" | "oauth";

const OAUTH_CALLBACK_PATH = "/craft/v1/apps/oauth/callback";

// The auth template every OAuth custom app uses (RFC 6750 bearer usage — what
// all built-in providers use too). The form doesn't ask; the backend keeps the
// template configurable for future exotic cases.
const BEARER_TEMPLATE: Record<string, string> = {
  Authorization: "Bearer {access_token}",
};

interface CreateCustomAppModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful create/edit so callers can refresh their list. */
  onSaved: () => void;
  /** Null → create a new custom app; non-null → edit that app's config. */
  existingApp: ExternalAppAdminResponse | null;
}

/** Collapse a key-value list into a record, dropping rows with an empty key. */
function toRecord(items: KeyValue[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of items) {
    const trimmedKey = key.trim();
    if (trimmedKey) out[trimmedKey] = value;
  }
  return out;
}

/** Expand a record into editable rows, seeding one empty row when empty. */
function toKeyValues(record: Record<string, string>): KeyValue[] {
  const entries = Object.entries(record).map(([key, value]) => ({
    key,
    value,
  }));
  return entries.length > 0 ? entries : [{ key: "", value: "" }];
}

export default function CreateCustomAppModal({
  open,
  onClose,
  onSaved,
  existingApp,
}: CreateCustomAppModalProps) {
  const isEdit = existingApp !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>([]);
  const [headers, setHeaders] = useState<KeyValue[]>([{ key: "", value: "" }]);
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [authMethod, setAuthMethod] = useState<AuthMethod>("static");
  const [authorizeUrl, setAuthorizeUrl] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [scope, setScope] = useState("");
  const [scopeParam, setScopeParam] = useState("scope");
  const [extraAuthorizeParams, setExtraAuthorizeParams] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [tokenAuthMethod, setTokenAuthMethod] =
    useState<TokenEndpointAuthMethod>("client_secret_post");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [copiedRedirectUri, setCopiedRedirectUri] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Re-seed every time the modal opens: from the existing app when editing,
  // blank when creating. Prevents a prior attempt from leaking in.
  useEffect(() => {
    if (!open) return;
    const oauth = existingApp?.oauth_config ?? null;
    const existingOrg = existingApp?.organization_credentials ?? {};
    setName(existingApp?.name ?? "");
    setDescription(existingApp?.description ?? "");
    setUpstreamPatterns(existingApp?.upstream_url_patterns ?? []);
    setHeaders(
      existingApp
        ? toKeyValues(existingApp.auth_template)
        : [{ key: "", value: "" }]
    );
    // client_id/client_secret get dedicated inputs in OAuth mode; keep them
    // out of the generic editor so they don't show twice.
    setOrgCredentials(
      toKeyValues(
        Object.fromEntries(
          Object.entries(existingOrg).filter(
            ([key]) =>
              !oauth || (key !== "client_id" && key !== "client_secret")
          )
        )
      )
    );
    setAuthMethod(oauth ? "oauth" : "static");
    setAuthorizeUrl(oauth?.authorize_url ?? "");
    setTokenUrl(oauth?.token_url ?? "");
    setScope(oauth?.scope ?? "");
    setScopeParam(oauth?.scope_param ?? "scope");
    setExtraAuthorizeParams(toKeyValues(oauth?.extra_authorize_params ?? {}));
    setTokenAuthMethod(
      oauth?.token_endpoint_auth_method ?? "client_secret_post"
    );
    setClientId(oauth ? (existingOrg.client_id ?? "") : "");
    setClientSecret(oauth ? (existingOrg.client_secret ?? "") : "");
    setCopiedRedirectUri(false);
    setFile(null);
    setError(null);
  }, [open, existingApp]);

  const redirectUri =
    (typeof window !== "undefined" ? window.location.origin : "") +
    OAUTH_CALLBACK_PATH;

  async function copyRedirectUri() {
    await navigator.clipboard.writeText(redirectUri);
    setCopiedRedirectUri(true);
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required. A bundle is required only on create (optional on edit).
  const disabledCreateReason = (() => {
    if (isSaving) return "Save is already in progress.";
    if (name.trim().length === 0) {
      return "Enter a name before creating this custom app.";
    }
    if (upstreamPatterns.length === 0) {
      return "Add at least one upstream URL pattern. Type a pattern and press Enter.";
    }
    if (authMethod === "oauth") {
      if (!authorizeUrl.trim().startsWith("https://")) {
        return "Enter the provider's authorization URL (must be https://).";
      }
      if (!tokenUrl.trim().startsWith("https://")) {
        return "Enter the provider's token URL (must be https://).";
      }
    }
    if (!isEdit && file === null) {
      return "Upload a bundle .zip file before creating this custom app.";
    }
    return null;
  })();
  const createButton = (
    <Button onClick={save} disabled={disabledCreateReason !== null}>
      {isSaving
        ? isEdit
          ? "Saving…"
          : "Creating…"
        : isEdit
          ? "Save"
          : "Create"}
    </Button>
  );

  async function save() {
    setIsSaving(true);
    setError(null);

    const oauthConfig: CustomOAuthConfig | null =
      authMethod === "oauth"
        ? {
            authorize_url: authorizeUrl.trim(),
            token_url: tokenUrl.trim(),
            scope: scope.trim(),
            scope_param: scopeParam.trim() || "scope",
            extra_authorize_params: toRecord(extraAuthorizeParams),
            token_endpoint_auth_method: tokenAuthMethod,
          }
        : null;
    // OAuth mode is fully prescribed: the bearer template, and exactly the
    // client credentials as org credentials (the keys the OAuth routes read).
    const authTemplate = oauthConfig ? BEARER_TEMPLATE : toRecord(headers);
    const orgCredentialsRecord: Record<string, string> = oauthConfig
      ? {}
      : toRecord(orgCredentials);
    if (oauthConfig) {
      if (clientId.trim()) orgCredentialsRecord.client_id = clientId.trim();
      if (clientSecret.trim()) {
        orgCredentialsRecord.client_secret = clientSecret.trim();
      }
    }

    // Edit is two calls (bundle + fields); track the bundle step to message
    // partial success accurately.
    let bundleSaved = false;
    try {
      if (existingApp) {
        // Bundle first (the failure-prone step): a failure here leaves fields
        // unsent. Clear the file so a retry doesn't re-upload it.
        if (file) {
          await replaceCustomAppBundle(existingApp.id, file);
          setFile(null);
          bundleSaved = true;
        }
        // enabled is toggled separately on the card. oauth_config is always
        // sent: an explicit null switches the app back to static credentials.
        await updateExternalApp(existingApp.id, {
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: authTemplate,
          organization_credentials: orgCredentialsRecord,
          oauth_config: oauthConfig,
        });
      } else {
        // Create: bundle is required (enforced by `canSave`).
        await createCustomExternalApp({
          name: name.trim(),
          description: description.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: authTemplate,
          organization_credentials: orgCredentialsRecord,
          enabled: true,
          bundle: file!,
          ...(oauthConfig ? { oauth_config: oauthConfig } : {}),
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      // A step may have committed; refresh the list to reflect what persisted.
      onSaved();
      const detail = e instanceof Error ? e.message : String(e);
      setError(
        bundleSaved
          ? `The new bundle was saved, but updating the other fields failed — retry to finish: ${detail}`
          : detail
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={existingApp ? `Edit ${existingApp.name}` : "Create custom app"}
          description={
            isEdit
              ? "Update this custom app's configuration, and optionally upload a new bundle to replace its files."
              : "Define a custom external app: upload its skill bundle and configure how the egress proxy authenticates outbound requests."
          }
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Name</Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Custom App"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Description</Text>
              <InputTypeIn
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional — defaults to the bundle's SKILL.md description"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Upstream URL patterns</Text>
              <Text font="secondary-body" color="text-03">
                {
                  "Outbound URLs the proxy may inject credentials into. Use * to match any characters (e.g. https://api.example.com/* covers every path on that host). The host must be literal — no wildcards before the first slash. Type a pattern and press Enter."
                }
              </Text>
              <ListFieldInput
                values={upstreamPatterns}
                onChange={setUpstreamPatterns}
                placeholder="https://api.example.com/*"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Authentication</Text>
              <Text font="secondary-body" color="text-03">
                How users connect to this app: static headers they (or your org)
                fill in, or an OAuth 2.0 authorization-code flow against the
                provider.
              </Text>
              <Tabs
                value={authMethod}
                onValueChange={(value) => setAuthMethod(value as AuthMethod)}
              >
                <Tabs.List>
                  <Tabs.Trigger value="static">Static headers</Tabs.Trigger>
                  <Tabs.Trigger value="oauth">OAuth 2.0</Tabs.Trigger>
                </Tabs.List>
                <div className="pt-3">
                  <Tabs.Content value="static">
                    <div className="flex flex-col gap-4">
                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">
                          Header credential pattern
                        </Text>
                        <Text font="secondary-body" color="text-03">
                          {`Optional — headers injected into outbound requests. Use {placeholder} for values the user (or org below) supplies, e.g. "Bearer {api_key}". Leave empty to allowlist the upstream patterns without injecting credentials.`}
                        </Text>
                        <InputKeyValue
                          keyTitle="Header"
                          valueTitle="Value"
                          keyPlaceholder="Authorization"
                          valuePlaceholder="Bearer {api_key}"
                          items={headers}
                          onChange={setHeaders}
                          mode="line"
                          addButtonLabel="Add header"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">
                          Organization credentials
                        </Text>
                        <Text font="secondary-body" color="text-03">
                          Optional — values your org pre-fills for every user.
                          Leave empty for apps where each user supplies their
                          own credentials.
                        </Text>
                        <InputKeyValue
                          keyTitle="Credential key"
                          valueTitle="Value"
                          keyPlaceholder="api_key"
                          valuePlaceholder="sk-…"
                          items={orgCredentials}
                          onChange={setOrgCredentials}
                          mode="line"
                          addButtonLabel="Add credential"
                        />
                      </div>
                    </div>
                  </Tabs.Content>

                  <Tabs.Content value="oauth">
                    <div className="flex flex-col gap-4">
                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Redirect URI</Text>
                        <Text font="secondary-body" color="text-03">
                          Register this callback URL in the provider&apos;s
                          OAuth app settings.
                        </Text>
                        <div className="flex items-center gap-2">
                          <Text font="main-ui-body" color="text-03">
                            {redirectUri}
                          </Text>
                          <Button
                            prominence="secondary"
                            onClick={copyRedirectUri}
                          >
                            {copiedRedirectUri ? "Copied" : "Copy"}
                          </Button>
                        </div>
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Authorization URL</Text>
                        <InputTypeIn
                          value={authorizeUrl}
                          onChange={(e) => setAuthorizeUrl(e.target.value)}
                          placeholder="https://provider.example.com/oauth/authorize"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Token URL</Text>
                        <InputTypeIn
                          value={tokenUrl}
                          onChange={(e) => setTokenUrl(e.target.value)}
                          placeholder="https://provider.example.com/oauth/token"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Scopes</Text>
                        <Text font="secondary-body" color="text-03">
                          Exactly as the provider expects them (often
                          space-separated). Leave empty to use the
                          provider&apos;s defaults.
                        </Text>
                        <InputTypeIn
                          value={scope}
                          onChange={(e) => setScope(e.target.value)}
                          placeholder="read write"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Client ID</Text>
                        <InputTypeIn
                          value={clientId}
                          onChange={(e) => setClientId(e.target.value)}
                          placeholder="From the provider's OAuth app settings"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Client secret</Text>
                        <InputTypeIn
                          value={clientSecret}
                          onChange={(e) => setClientSecret(e.target.value)}
                          placeholder="Treat this like a password"
                        />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Token endpoint auth</Text>
                        <Text font="secondary-body" color="text-03">
                          Most providers take the client credentials in the
                          request body; some require an HTTP Basic header
                          instead.
                        </Text>
                        <InputSelect
                          value={tokenAuthMethod}
                          onValueChange={(value) =>
                            setTokenAuthMethod(value as TokenEndpointAuthMethod)
                          }
                        >
                          <InputSelect.Trigger />
                          <InputSelect.Content>
                            <InputSelect.Item value="client_secret_post">
                              Request body (client_secret_post)
                            </InputSelect.Item>
                            <InputSelect.Item value="client_secret_basic">
                              Basic auth header (client_secret_basic)
                            </InputSelect.Item>
                          </InputSelect.Content>
                        </InputSelect>
                      </div>

                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">
                          Extra authorization parameters
                        </Text>
                        <Text font="secondary-body" color="text-03">
                          {`Optional — added to the authorize URL (response_type=code is always sent). E.g. access_type=offline for providers that gate refresh tokens behind it.`}
                        </Text>
                        <InputKeyValue
                          keyTitle="Parameter"
                          valueTitle="Value"
                          keyPlaceholder="access_type"
                          valuePlaceholder="offline"
                          items={extraAuthorizeParams}
                          onChange={setExtraAuthorizeParams}
                          mode="line"
                          addButtonLabel="Add parameter"
                        />
                      </div>

                      <Text font="secondary-body" color="text-03">
                        {
                          "Matching outbound requests are authenticated with “Authorization: Bearer <the user's access token>”."
                        }
                      </Text>
                    </div>
                  </Tabs.Content>
                </div>
              </Tabs>
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">
                {isEdit ? "Replace bundle (.zip)" : "Bundle (.zip)"}
              </Text>
              <Text font="secondary-body" color="text-03">
                {isEdit
                  ? "Optional — upload a new zip to replace the current bundle. Leave empty to keep it. The slug stays the same."
                  : "A zip containing SKILL.md plus any other files. The filename becomes the app slug."}
              </Text>
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <Button
                  icon={SvgUploadCloud}
                  prominence="secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {file
                    ? "Change file"
                    : isEdit
                      ? "Choose new zip"
                      : "Choose zip"}
                </Button>
                <Text font="main-ui-body" color="text-03">
                  {file
                    ? file.name
                    : isEdit
                      ? "Keeping current bundle"
                      : "No file selected"}
                </Text>
              </div>
            </div>

            {error && (
              <MessageCard
                variant="error"
                title="Couldn't save"
                description={error}
              />
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <div className="flex justify-end gap-2 w-full">
            <Button
              prominence="secondary"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </Button>
            {disabledCreateReason ? (
              <Tooltip tooltip={disabledCreateReason}>
                <span className="inline-flex">{createButton}</span>
              </Tooltip>
            ) : (
              createButton
            )}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

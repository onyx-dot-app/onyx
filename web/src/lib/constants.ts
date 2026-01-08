export enum AuthType {
  DISABLED = "disabled",
  BASIC = "basic",
  GOOGLE_OAUTH = "google_oauth",
  OIDC = "oidc",
  SAML = "saml",
  CLOUD = "cloud",
}

export const HOST_URL = process.env.WEB_DOMAIN || "http://127.0.0.1:3000";

export const INTERNAL_URL = process.env.INTERNAL_URL || "http://127.0.0.1:8080";

// Documentation URLs
export const DOCS_BASE_URL = "https://docs.onyx.app";
export const DOCS_ADMINS_PATH = `${DOCS_BASE_URL}/admins`;

export const MCP_INTERNAL_URL =
  process.env.MCP_INTERNAL_URL || "http://127.0.0.1:8090";

// NOTE: this should ONLY be used on the server-side (including middleware).
// The AUTH_TYPE environment variable is set in the backend and shared with Next.js
export const SERVER_SIDE_ONLY__AUTH_TYPE = (process.env.AUTH_TYPE ||
  AuthType.DISABLED) as AuthType;

export const NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED =
  process.env.NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED?.toLowerCase() ===
  "true";

export const TENANT_ID_COOKIE_NAME = "onyx_tid";

export const GMAIL_AUTH_IS_ADMIN_COOKIE_NAME = "gmail_auth_is_admin";

export const GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME =
  "google_drive_auth_is_admin";

export const SEARCH_TYPE_COOKIE_NAME = "search_type";
export const AGENTIC_SEARCH_TYPE_COOKIE_NAME = "agentic_type";

export const LOGOUT_DISABLED =
  process.env.NEXT_PUBLIC_DISABLE_LOGOUT?.toLowerCase() === "true";

// Default sidebar open is true if the environment variable is not set
export const NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN =
  process.env.NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN?.toLowerCase() === "false"
    ? false
    : true;

export const TOGGLED_CONNECTORS_COOKIE_NAME = "toggled_connectors";

/* Enterprise-only settings */
export const NEXT_PUBLIC_CUSTOM_REFRESH_URL =
  process.env.NEXT_PUBLIC_CUSTOM_REFRESH_URL;

// NOTE: this should ONLY be used on the server-side. If used client side,
// it will not be accurate (will always be false).
export const SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED =
  process.env.ENABLE_PAID_ENTERPRISE_EDITION_FEATURES?.toLowerCase() === "true";
// NOTE: since this is a `NEXT_PUBLIC_` variable, it will be set at
// build-time
// TODO: consider moving this to an API call so that the api_server
// can be the single source of truth
export const EE_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES?.toLowerCase() === "true";

export const CUSTOM_ANALYTICS_ENABLED = process.env.CUSTOM_ANALYTICS_SECRET_KEY
  ? true
  : false;

export const GTM_ENABLED =
  process.env.NEXT_PUBLIC_GTM_ENABLED?.toLowerCase() === "true";

export const DISABLE_LLM_DOC_RELEVANCE =
  process.env.DISABLE_LLM_DOC_RELEVANCE?.toLowerCase() === "true";

export const NEXT_PUBLIC_CLOUD_ENABLED =
  process.env.NEXT_PUBLIC_CLOUD_ENABLED?.toLowerCase() === "true";

export const REGISTRATION_URL =
  process.env.INTERNAL_URL || "http://127.0.0.1:3001";

export const SERVER_SIDE_ONLY__CLOUD_ENABLED =
  process.env.NEXT_PUBLIC_CLOUD_ENABLED?.toLowerCase() === "true";

export const NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED =
  process.env.NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED?.toLowerCase() === "true" &&
  !NEXT_PUBLIC_CLOUD_ENABLED;

export const NEXT_PUBLIC_TEST_ENV =
  process.env.NEXT_PUBLIC_TEST_ENV?.toLowerCase() === "true";

export const NEXT_PUBLIC_ENABLE_CHROME_EXTENSION =
  process.env.NEXT_PUBLIC_ENABLE_CHROME_EXTENSION?.toLowerCase() === "true";

export const NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK =
  process.env.NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK?.toLowerCase() ===
  "true";

export const NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;

// Restrict markdown links to safe protocols
export const ALLOWED_URL_PROTOCOLS = ["http:", "https:", "mailto:"] as const;

// Agent/Persona related constants
export const MAX_CHARACTERS_PERSONA_DESCRIPTION = 5000000;
export const MAX_CHARACTERS_AGENT_DESCRIPTION = 500;
export const MAX_STARTER_MESSAGES = 4;
export const MAX_CHARACTERS_STARTER_MESSAGE = 200;
export const STARTER_MESSAGES_EXAMPLES = [
  "Give me an overview of some documents.",
  "Find the latest sales report.",
  "Compile a list of our engineering goals for this quarter.",
  "Summarize my goals for today.",
];

//Credential form data key constants
export const CREDENTIAL_NAME = "name";
export const CREDENTIAL_SOURCE = "source";
export const CREDENTIAL_UPLOADED_FILE = "uploaded_file";
export const CREDENTIAL_FIELD_KEY = "field_key";
export const CREDENTIAL_TYPE_DEFINITION_KEY = "type_definition_key";
export const CREDENTIAL_JSON = "credential_json";

export const MODAL_ROOT_ID = "modal-root";

export const ANONYMOUS_USER_NAME = "Anonymous";
export const UNNAMED_CHAT = "New Chat";

export const DEFAULT_ASSISTANT_ID = 0;
export const GENERAL_ASSISTANT_ID = -1;
export const IMAGE_ASSISTANT_ID = -2;
export const ART_ASSISTANT_ID = -3;

// Used in the File Picker to show a max number of files.
// The rest will be hidden behind an "All Recent Files" button.
export const MAX_FILES_TO_SHOW = 3;

// SIZES
export const MOBILE_SIDEBAR_BREAKPOINT_PX = 640;
export const DEFAULT_AGENT_AVATAR_SIZE_PX = 18;
export const HORIZON_DISTANCE_PX = 800;
export const LOGO_FOLDED_SIZE_PX = 24;
export const LOGO_UNFOLDED_SIZE_PX = 88;

export const DEFAULT_CONTEXT_TOKENS = 120_000;
export const MAX_CHUNKS_FED_TO_CHAT = 25;

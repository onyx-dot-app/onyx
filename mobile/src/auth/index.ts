// Public surface of the auth module. Import from "@/auth".
//
// Wiring: clientConfig.getAuthHeaders = getAuthHeaders (query/client.ts); wrap the app
// in <AuthProvider> (app/_layout.tsx); auth screens read useAuth(); on a 401/403 call
// useAuth().signOut() + route to login.
export { AuthProvider, useAuth } from "./AuthProvider";
export type { AuthContextValue, AuthStatus } from "./AuthProvider";

export { getAuthHeaders } from "./getAuthHeaders";

export {
  loginWithPassword,
  loginWithGoogle,
  register,
  logout,
  extractTokenFromUrl,
  AuthError,
  InvalidCredentialsError,
  RegistrationError,
  SignInCancelledError,
  AUTH_REDIRECT_URL,
  MOBILE_LOGIN_PATH,
  REGISTER_PATH,
  GOOGLE_OAUTH_AUTHORIZE_PATH,
  REFRESH_PATH,
  LOGOUT_PATH,
} from "./authClient";

export { getToken, setToken, deleteToken, JWT_STORAGE_KEY } from "./secureStore";

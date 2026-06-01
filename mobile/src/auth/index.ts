// Public surface of the auth module. Import from "@/auth".
//
// Integrator checklist:
//   (a) clientConfig.getAuthHeaders = getAuthHeaders  (in query/client.ts)
//   (b) wrap the app: <AuthProvider> in app/_layout.tsx
//   (c) (auth)/login.tsx -> useAuth().signInWithPassword / signInWithGoogle;
//       (auth)/register.tsx -> useAuth().register;
//       (auth)/callback.tsx -> reflects useAuth().status for cold-start OAuth;
//       app/index.tsx redirects by useAuth().status.
//   (d) on a 401/403 from any request, call useAuth().signOut() + route to login.
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

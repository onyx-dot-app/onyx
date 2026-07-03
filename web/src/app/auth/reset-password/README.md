# Password Reset Flow

Two pages cooperate to reset a user's password. The user keeps the first tab
open while the second tab (opened from their inbox) performs the reset.

The views live in `web/src/views/auth/password-reset/`. The app-router pages
under `web/src/app/auth/forgot-password/` and `web/src/app/auth/reset-password/`
are thin re-exports.

---

## Pages

### `ForgotPasswordPage` — `/auth/forgot-password?email=...`

The **originating tab**. Reached from the "Forgot password?" link on the
login form, which pre-populates `?email=` from what the user typed.

- Fires `forgotPassword(email)` once on mount to dispatch the reset email.
- Displays a "Check your inbox" card with a "Resend" link (`?reset=true`).
- Listens on `BroadcastChannel("password-reset")`. When a `"success"`
  message arrives (broadcast by the reset tab), it redirects to `/auth/login`.

**Guards:**
- `NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED` is false, or no `?email=` param →
  redirect to `/auth/login`

### `ResetPasswordPage` — `/auth/reset-password?token=...&email=...`

The **action tab**, opened from the reset email link. Both `token` and `email`
are present in the URL — `token` authenticates the request; `email` is
included so this page can display which account is being reset.

- Shows a form with "New Password" and "Confirm Password" fields.
- On success: broadcasts `"success"` on `BroadcastChannel("password-reset")`,
  then replaces the form with a success message ("You can close this tab now").
- On error: toasts the failure message; the form stays interactive.

**Guards:**
- `NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED` is false, or no `?token=`, or no
  `?email=` → redirect to `/auth/login`

---

## Navigating without going through the proper flow

| Scenario | Outcome |
|---|---|
| Visit `/auth/forgot-password` without `?email=` | Redirect to `/auth/login` |
| Visit `/auth/reset-password` without `?token=` or `?email=` | Redirect to `/auth/login` |
| Visit `/auth/reset-password` with an expired or invalid token | Form submits, backend returns an error, toast is shown |
| Open the reset link after already using it | Same as above — token is already consumed |

---

## Tab communication: `BroadcastChannel`

`ForgotPasswordPage` detects completion via the
[BroadcastChannel API](https://developer.mozilla.org/en-US/docs/Web/API/BroadcastChannel)
rather than server polling.

**Why BroadcastChannel here, not polling:**

The user is **not logged in** during the password reset flow, so there is no
authenticated session and no server-side state (equivalent to `is_verified`)
to poll against. Adding a polling endpoint would require either exposing
token-state over an unauthenticated API (a security concern) or some other
out-of-band mechanism.

`BroadcastChannel` is a same-origin, same-browser messaging primitive — a
natural fit here because:

1. **No authenticated session required** — it works entirely in the browser,
   without any server round-trips.
2. **The scenario is inherently same-browser** — the user clicks a link from
   their email client into the same browser where tab 1 is open. Cross-device
   resets are not a concern: if the user resets on a different device, they
   can simply navigate to `/auth/login` manually (tab 1 will never receive the
   broadcast, but the reset itself still succeeds).

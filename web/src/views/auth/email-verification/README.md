# Email Verification Flow

Two pages cooperate to verify a user's email address. The user keeps the
first tab open while the second tab (opened from their inbox) performs the
verification.

---

## Pages

### `SendEmailVerificationPage` — `/auth/send-email-verification`

The **originating tab**. Shown to logged-in users who have not yet verified
their email address.

- Fires `requestEmailVerification` once on mount to send the verification email.
- Displays a "Check your inbox" card with a "Resend" link (`?resend=true`).
- Polls `mutateUser()` every 3 seconds. When `user.is_verified` becomes
  `true`, it redirects to `/app`.

**Guards:**
- Not logged in → `/auth/login`
- Already verified, or verification not required → `/app`

### `VerifyEmailPage` — `/auth/verify-email?token=...`

The **action tab**, opened from the email link. Calls `verifyEmail(token)`
once on mount.

- While verifying: shows a neutral "Verifying your token…" message.
- On success: shows a success message ("You can now close this tab").
- On error: toasts the failure and redirects to `/app` (logged in) or
  `/auth/login` (not logged in).

**Guards:**
- No `token` param → `/auth/send-email-verification`

---

## Navigating without going through the proper flow

| Scenario | Outcome |
|---|---|
| Visit `/auth/send-email-verification` while already verified | Redirect to `/app` |
| Visit `/auth/send-email-verification` while logged out | Redirect to `/auth/login` |
| Visit `/auth/verify-email` without a `?token=` param | Redirect to `/auth/send-email-verification` |
| Visit `/auth/verify-email` with an invalid or expired token | Toast error, redirect to `/app` or `/auth/login` |

---

## Tab communication: server polling via `mutateUser()`

`SendEmailVerificationPage` detects completion by polling the server (SWR
`mutateUser()`) every 3 seconds rather than using a browser-level signal.

**Why polling here, not BroadcastChannel:**

The user is **logged in** during email verification, so their `is_verified`
state lives on the server and is accessible at any time. Polling is the right
tool because:

1. **Resilient to tab lifecycle** — if the user closes and reopens tab 1, or
   reloads the page, the next poll immediately reflects the current server
   state. A broadcast message would have been lost.
2. **Cross-device** — verification can happen on a phone or a different
   browser entirely. A `BroadcastChannel` is same-browser-only; a server poll
   catches all cases.

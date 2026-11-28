import MagicLinkRedeem from "@/app/auth/magic-link/MagicLinkRedeem";

/** Opened from the sign-in email. The token is redeemed here, by a POST, so a
 * mail scanner that fetches the link cannot use it up. */
export default function Page() {
  return <MagicLinkRedeem />;
}

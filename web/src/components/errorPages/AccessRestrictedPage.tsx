"use client";

import { useState } from "react";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { fetchCustomerPortal } from "@/lib/billing/utils";
import { useRouter } from "next/navigation";
import Button from "@/refresh-components/buttons/Button";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { logout } from "@/lib/user";
import { loadStripe } from "@stripe/stripe-js";
import {
  NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName = "text-action-link-05 hover:text-action-link-06";
const fetchResubscriptionSession = async () => {
  const response = await fetch("/api/tenants/create-subscription-session", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    throw new Error("Failed to create resubscription session");
  }
  return response.json();
};

export default function AccessRestricted() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const handleManageSubscription = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchCustomerPortal();

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          `Failed to create customer portal session: ${
            errorData.message || response.statusText
          }`
        );
      }

      const { url } = await response.json();

      if (!url) {
        throw new Error("No portal URL returned from the server");
      }

      router.push(url);
    } catch (error) {
      console.error("Error creating customer portal session:", error);
      setError("Error opening customer portal. Please try again later.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResubscribe = async () => {
    setIsLoading(true);
    setError(null);
    if (!NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY) {
      setError("Stripe public key not found");
      setIsLoading(false);
      return;
    }
    try {
      const { sessionId } = await fetchResubscriptionSession();
      const stripe = await loadStripe(NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY);

      if (stripe) {
        await stripe.redirectToCheckout({ sessionId });
      } else {
        throw new Error("Stripe failed to load");
      }
    } catch (error) {
      console.error("Error creating resubscription session:", error);
      setError("Error opening resubscription page. Please try again later.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>Access Restricted</Text>
        <SvgLock className="stroke-status-error-05 w-[1.5rem] h-[1.5rem]" />
      </div>

      <Text text03>
        Your access to Onyx has been temporarily suspended due to a lapse in
        your subscription.
      </Text>

      {NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>
            To reinstate your access and continue benefiting from Onyx&apos;s
            powerful features, please update your payment information.
          </Text>

          <Text text03>
            If you&apos;re an admin, you can manage your subscription by
            clicking the button below. For other users, please reach out to your
            administrator to address this matter.
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleResubscribe} disabled={isLoading}>
              {isLoading ? "Loading..." : "Resubscribe"}
            </Button>
            <Button
              secondary
              onClick={handleManageSubscription}
              disabled={isLoading}
            >
              Manage Existing Subscription
            </Button>
            <Button
              secondary
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>

          {error && <Text className="text-status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text text03>
            To reinstate your access and continue using Onyx, please contact
            your system administrator to renew your license.
          </Text>

          <Text text03>
            If you are the administrator, please visit the{" "}
            <Link className={linkClassName} href="/ee/admin/billing">
              Admin Billing
            </Link>{" "}
            page to update your license, or reach out to{" "}
            <a className={linkClassName} href="mailto:support@onyx.app">
              support@onyx.app
            </a>{" "}
            to renew your subscription.
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>
        </>
      )}

      <Text text03>
        Need help? Join our{" "}
        <InlineExternalLink
          className={linkClassName}
          href="https://discord.gg/4NA5SbzrWb"
        >
          Discord community
        </InlineExternalLink>{" "}
        for support.
      </Text>
    </ErrorPageLayout>
  );
}

"use client";
import { FiLock } from "react-icons/fi";
import ErrorPageLayout from "./ErrorPageLayout";
import { fetchCustomerPortal } from "@/app/ee/admin/billing/utils";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/user";
import { loadStripe } from "@stripe/stripe-js";
import { NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY } from "@/lib/constants";

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
      <h1 className="text-2xl font-semibold flex items-center gap-2 mb-4 text-gray-800 dark:text-gray-200">
        <p>Access Restricted</p>
        <FiLock className="text-error inline-block" />
      </h1>
      <div className="space-y-4 text-gray-600 dark:text-gray-300">
        <p>
          We regret to inform you that your access to Onyx has been temporarily
          suspended due to a lapse in your subscription.
        </p>
        <p>
          To reinstate your access and continue benefiting from Onyx&apos;s
          powerful features, please update your payment information.
        </p>
        <p>
          If you&apos;re an admin, you can manage your subscription by clicking
          the button below. For other users, please reach out to your
          administrator to address this matter.
        </p>
        <div className="flex flex-col space-y-4 sm:flex-row sm:space-y-0 sm:space-x-4">
          <Button
            onClick={handleResubscribe}
            disabled={isLoading}
            className="w-full sm:w-auto"
          >
            {isLoading ? "Loading..." : "Resubscribe"}
          </Button>
          <Button
            variant="outline"
            onClick={handleManageSubscription}
            disabled={isLoading}
            className="w-full sm:w-auto"
          >
            Manage Existing Subscription
          </Button>
          <Button
            variant="outline"
            onClick={async () => {
              await logout();
              window.location.reload();
            }}
            className="w-full sm:w-auto"
          >
            Log out
          </Button>
        </div>
        {error && <p className="text-error">{error}</p>}
        <p>
          Need help? Join our{" "}
          <a
            className="text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            href="https://join.slack.com/t/danswer/shared_invite/zt-1w76msxmd-HJHLe3KNFIAIzk_0dSOKaQ"
            target="_blank"
            rel="noopener noreferrer"
          >
            Slack community
          </a>{" "}
          for support.
        </p>
      </div>
    </ErrorPageLayout>
  );
}

"use client";

import { useEffect } from "react";
import { toast } from "@/hooks/useToast";
import {
  createCustomerPortalSession,
  useBillingInformation,
  hasActiveSubscription,
} from "@/lib/billing";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import Button from "@/refresh-components/buttons/Button";
import { SubscriptionSummary } from "./SubscriptionSummary";
import { BillingAlerts } from "./BillingAlerts";
import { SvgClipboard, SvgWallet } from "@opal/icons";
export default function BillingInformationPage() {
  const {
    data: billingInformation,
    error,
    isLoading,
  } = useBillingInformation();

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("session_id")) {
      toast.success(
        "Congratulations! Your subscription has been updated successfully."
      );
      url.searchParams.delete("session_id");
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  if (isLoading) {
    return <div className="text-center py-8">Loading...</div>;
  }

  if (error) {
    console.error("Failed to fetch billing information:", error);
    return (
      <div className="text-center py-8 text-red-500">
        Error loading billing information. Please try again later.
      </div>
    );
  }

  if (!billingInformation || !hasActiveSubscription(billingInformation)) {
    return (
      <div className="text-center py-8">No billing information available.</div>
    );
  }

  const handleManageSubscription = async () => {
    try {
      const response = await createCustomerPortalSession();
      console.log("response", response);
      if (!response.stripe_customer_portal_url) {
        throw new Error("No portal URL returned from the server");
      }
      window.location.href = response.stripe_customer_portal_url;
    } catch (error) {
      console.error("Error creating customer portal session:", error);
      toast.error("Error creating customer portal session");
    }
  };

  return (
    <div className="space-y-8">
      <Card className="shadow-md">
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <SvgWallet className="mr-4 text-muted-foreground h-6 w-6" />
            Subscription Details
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <SubscriptionSummary billingInformation={billingInformation} />
          <BillingAlerts billingInformation={billingInformation} />
        </CardContent>
      </Card>

      <Card className="shadow-md">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">
            Manage Subscription
          </CardTitle>
          <CardDescription>
            View your plan, update payment, or change subscription
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={handleManageSubscription}
            className="w-full"
            leftIcon={SvgClipboard}
          >
            Manage Subscription
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

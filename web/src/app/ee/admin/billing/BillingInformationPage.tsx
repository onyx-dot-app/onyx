"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  fetchCustomerPortal,
  useBillingInformation,
} from "@/lib/billing/utils";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CreditCard, ArrowFatUp } from "@phosphor-icons/react";
import { SubscriptionSummary } from "./SubscriptionSummary";
import { BillingAlerts } from "./BillingAlerts";

export default function BillingInformationPage() {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const {
    data: billingInformation,
    error,
    isLoading,
  } = useBillingInformation();

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("session_id")) {
      setPopup({
        message:
          "Congratulations! Your subscription has been updated successfully.",
        type: "success",
      });
      url.searchParams.delete("session_id");
      window.history.replaceState({}, "", url.toString());
    }
  }, [setPopup]);

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

  if (!billingInformation) {
    return (
      <div className="text-center py-8">No billing information available.</div>
    );
  }

  const handleManageSubscription = async () => {
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
      setPopup({
        message: "Error creating customer portal session",
        type: "error",
      });
    }
  };

  return (
    <div className="space-y-8">
      {popup}
      <Card className="shadow-md">
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <CreditCard className="mr-4 text-muted-foreground" size={24} />
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
          <Button onClick={handleManageSubscription} className="w-full">
            <ArrowFatUp className="mr-2" size={16} />
            Manage Subscription
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

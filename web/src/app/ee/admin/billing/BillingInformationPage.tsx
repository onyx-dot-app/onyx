"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { fetchCustomerPortal, useBillingInformation } from "./utils";

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
    return <div className="text-center py-8">{i18n.t(k.LOADING)}</div>;
  }

  if (error) {
    console.error("Failed to fetch billing information:", error);
    return (
      <div className="text-center py-8 text-red-500">
        {i18n.t(k.ERROR_LOADING_BILLING_INFORMAT)}
      </div>
    );
  }

  if (!billingInformation) {
    return (
      <div className="text-center py-8">
        {i18n.t(k.NO_BILLING_INFORMATION_AVAILAB)}
      </div>
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
            {i18n.t(k.SUBSCRIPTION_DETAILS)}
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
            {i18n.t(k.MANAGE_SUBSCRIPTION)}
          </CardTitle>
          <CardDescription>
            {i18n.t(k.VIEW_YOUR_PLAN_UPDATE_PAYMENT)}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={handleManageSubscription} className="w-full">
            <ArrowFatUp className="mr-2" size={16} />
            {i18n.t(k.MANAGE_SUBSCRIPTION)}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

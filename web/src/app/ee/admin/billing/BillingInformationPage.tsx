"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
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
import { Button } from "@opal/components";
import { SubscriptionSummary } from "./SubscriptionSummary";
import { BillingAlerts } from "./BillingAlerts";
import { SvgClipboard, SvgWallet } from "@opal/icons";
export default function BillingInformationPage() {
  const t = useTranslations("admin.billing.info");
  const {
    data: billingInformation,
    error,
    isLoading,
  } = useBillingInformation();

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("session_id")) {
      toast.success(t("updatedToast.message"));
      url.searchParams.delete("session_id");
      window.history.replaceState({}, "", url.toString());
    }
  }, [t]);

  if (isLoading) {
    return <div className="text-center py-8">{t("loading.label")}</div>;
  }

  if (error) {
    console.error("Failed to fetch billing information:", error);
    return (
      <div className="text-center py-8 text-red-500">
        {t("loadError.message")}
      </div>
    );
  }

  if (!billingInformation || !hasActiveSubscription(billingInformation)) {
    return <div className="text-center py-8">{t("empty.message")}</div>;
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
      toast.error(t("portalError.message"));
    }
  };

  return (
    <div className="space-y-8">
      <Card className="shadow-md">
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <SvgWallet className="me-4 text-muted-foreground h-6 w-6" />
            {t("subscriptionDetails.title")}
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
            {t("manageSubscription.title")}
          </CardTitle>
          <CardDescription>
            {t("manageSubscription.description")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={handleManageSubscription}
            width="full"
            icon={SvgClipboard}
          >
            {t("manageSubscription.title")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

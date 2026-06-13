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
import { Button } from "@opal/components";
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
        "订阅已成功更新。"
      );
      url.searchParams.delete("session_id");
      window.history.replaceState({}, "", url.toString());
    }
  }, []);

  if (isLoading) {
    return <div className="text-center py-8">正在加载...</div>;
  }

  if (error) {
    console.error("Failed to fetch billing information:", error);
    return (
      <div className="text-center py-8 text-red-500">
        加载计费信息出错。请稍后重试。
      </div>
    );
  }

  if (!billingInformation || !hasActiveSubscription(billingInformation)) {
    return (
      <div className="text-center py-8">暂无可用计费信息。</div>
    );
  }

  const handleManageSubscription = async () => {
    try {
      const response = await createCustomerPortalSession();
      console.log("response", response);
      if (!response.stripe_customer_portal_url) {
        throw new Error("服务器未返回门户 URL");
      }
      window.location.href = response.stripe_customer_portal_url;
    } catch (error) {
      console.error("Error creating customer portal session:", error);
      toast.error("创建客户门户会话出错");
    }
  };

  return (
    <div className="space-y-8">
      <Card className="shadow-md">
        <CardHeader>
          <CardTitle className="text-2xl font-bold flex items-center">
            <SvgWallet className="mr-4 text-muted-foreground h-6 w-6" />
            订阅详情
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
            管理订阅
          </CardTitle>
          <CardDescription>
            查看套餐、更新付款方式或更改订阅
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={handleManageSubscription}
            width="full"
            icon={SvgClipboard}
          >
            管理订阅
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

import { BillingInformation } from "./interfaces";
import useSWR, { mutate } from "swr";

export const updateSubscriptionQuantity = async (seats: number) => {
  return await fetch("/api/tenants/update-subscription-quantity", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ quantity: seats }),
  });
};

export const fetchCustomerPortal = async () => {
  return await fetch("/api/tenants/create-customer-portal-session", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export const statusToDisplay = (status: string) => {
  switch (status) {
    case "trialing":
      return "Trialing";
    case "active":
      return "Active";
    case "canceled":
      return "Canceled";
    default:
      return "Unknown";
  }
};

export const useBillingInformation = () => {
  const url = "/api/tenants/billing-information";
  const swrResponse = useSWR<BillingInformation>(url, async (url: string) => {
    const res = await fetch(url);
    if (!res.ok) {
      const errorData = await res.json();
      throw new Error(
        errorData.message || "Failed to fetch billing information"
      );
    }
    return res.json();
  });

  return {
    ...swrResponse,
    refreshBillingInformation: () => mutate(url),
  };
};

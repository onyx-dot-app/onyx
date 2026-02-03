"use client";

import { redirect } from "next/navigation";

// TODO: Remove this redirect once all billing UI PRs are merged
// This page will contain the new billing UI, but for now we redirect
// to the old EE billing page to maintain backwards compatibility.
// PR 6 will remove this redirect and enable the new UI.

export default function BillingPage() {
  redirect("/ee/admin/billing");
}

"use client";

import { DateRangeSelector } from "../DateRangeSelector";
import { DanswerBotChart } from "./DanswerBotChart";
import { FeedbackChart } from "./FeedbackChart";
import { QueryPerformanceChart } from "./QueryPerformanceChart";
import { useTimeRange } from "../lib";
import { AdminPageTitle } from "@/components/admin/Title";
import { FiActivity } from "react-icons/fi";
import UsageReports from "./UsageReports";
import { Separator } from "@/components/ui/separator";

export default function AnalyticsPage() {
  const [timeRange, setTimeRange] = useTimeRange();

  return (
    <main className="pt-4 mx-auto container">
      <AdminPageTitle
        title="Usage Statistics"
        icon={<FiActivity size={32} />}
      />
      <DateRangeSelector
        value={timeRange}
        onValueChange={(value) => setTimeRange(value as any)}
      />
      <QueryPerformanceChart timeRange={timeRange} />
      <FeedbackChart timeRange={timeRange} />
      <DanswerBotChart timeRange={timeRange} />
      <Separator />
      <UsageReports />
    </main>
  );
}

"use client";

import { DateRangeSelector } from "../DateRangeSelector";
import { DanswerBotChart } from "./DanswerBotChart";
import { FeedbackChart } from "./FeedbackChart";
import { QueryPerformanceChart } from "./QueryPerformanceChart";
import { BarChartIcon } from "@/components/icons/icons";
import { useTimeRange } from "../lib";
import { AdminPageTitle } from "@/components/admin/Title";
import { FiActivity } from "react-icons/fi";
import UsageReports from "./UsageReports";
import { Divider } from "@tremor/react";

export default function AnalyticsPage() {
  const [timeRange, setTimeRange] = useTimeRange();

  return (
    <main className="pt-4 mx-auto container">
      {/* TODO: remove this `dark` once we have a mode selector */}
      <AdminPageTitle
        title="Usage Statistics"
        icon={<FiActivity size={32} />}
      />

      <DateRangeSelector value={timeRange} onValueChange={setTimeRange} />

      <QueryPerformanceChart timeRange={timeRange} />
      <FeedbackChart timeRange={timeRange} />
      <DanswerBotChart timeRange={timeRange} />
      <Divider />
      <UsageReports />
    </main>
  );
}

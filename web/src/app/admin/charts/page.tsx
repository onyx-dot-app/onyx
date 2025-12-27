"use client";

import React from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import Text from "@/refresh-components/texts/Text";

// Mock Data for Farm Analytics
const yieldData = [
  { year: "2018", wheat: 4000, corn: 2400, soy: 2400 },
  { year: "2019", wheat: 3000, corn: 1398, soy: 2210 },
  { year: "2020", wheat: 2000, corn: 9800, soy: 2290 },
  { year: "2021", wheat: 2780, corn: 3908, soy: 2000 },
  { year: "2022", wheat: 1890, corn: 4800, soy: 2181 },
  { year: "2023", wheat: 2390, corn: 3800, soy: 2500 },
  { year: "2024", wheat: 3490, corn: 4300, soy: 2100 },
];

const soilMoistureData = [
  { time: "00:00", moisture: 45 },
  { time: "04:00", moisture: 42 },
  { time: "08:00", moisture: 35 },
  { time: "12:00", moisture: 30 },
  { time: "16:00", moisture: 40 },
  { time: "20:00", moisture: 55 },
  { time: "23:59", moisture: 50 },
];

const resourceUsageData = [
  { name: "Irrigation", value: 450 },
  { name: "Fertilizers", value: 300 },
  { name: "Pesticides", value: 200 },
  { name: "Seeds", value: 250 },
  { name: "Labor", value: 150 },
];

const rainfallData = [
  { day: "Mon", mm: 12 },
  { day: "Tue", mm: 19 },
  { day: "Wed", mm: 3 },
  { day: "Thu", mm: 5 },
  { day: "Fri", mm: 2 },
  { day: "Sat", mm: 25 },
  { day: "Sun", mm: 15 },
];

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8"];

const ChartCard = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <div className="bg-background-tint-02 border border-border rounded-lg p-6 flex flex-col h-[400px]">
    <div className="mb-4">
      <Text headingH3>{title}</Text>
    </div>
    <div className="flex-1 w-full min-h-0">{children}</div>
  </div>
);

const FarmChartsPage = () => {
  return (
    <div className="w-full h-full overflow-y-auto p-8 bg-background">
      <div className="mb-8">
        <Text headingH1>Farm Analytics Dashboard</Text>
        <Text text02 className="text-text-500 mt-2">
          Overview of farm performance, soil health, and resource distribution.
        </Text>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-8">
        {/* Crop Yield Trends */}
        <ChartCard title="Annual Crop Yields (Tons)">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={yieldData}
              margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#374151"
                vertical={false}
              />
              <XAxis dataKey="year" stroke="#9CA3AF" />
              <YAxis stroke="#9CA3AF" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1F2937",
                  borderColor: "#374151",
                  color: "#F3F4F6",
                }}
                itemStyle={{ color: "#F3F4F6" }}
              />
              <Legend />
              <Bar dataKey="wheat" fill="#8884d8" radius={[4, 4, 0, 0]} name="Wheat" />
              <Bar dataKey="corn" fill="#82ca9d" radius={[4, 4, 0, 0]} name="Corn" />
              <Bar dataKey="soy" fill="#ffc658" radius={[4, 4, 0, 0]} name="Soy" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Soil Moisture Levels */}
        <ChartCard title="Daily Soil Moisture (%)">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={soilMoistureData}
              margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="colorMoisture" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.8} />
                  <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#374151"
                vertical={false}
              />
              <XAxis dataKey="time" stroke="#9CA3AF" />
              <YAxis stroke="#9CA3AF" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1F2937",
                  borderColor: "#374151",
                  color: "#F3F4F6",
                }}
              />
              <Area
                type="monotone"
                dataKey="moisture"
                stroke="#0ea5e9"
                fillOpacity={1}
                fill="url(#colorMoisture)"
                name="Moisture %"
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Resource Allocation */}
        <ChartCard title="Resource Allocation Costs">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={resourceUsageData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                outerRadius={120}
                fill="#8884d8"
                dataKey="value"
              >
                {resourceUsageData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={COLORS[index % COLORS.length]}
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1F2937",
                  borderColor: "#374151",
                  color: "#F3F4F6",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Rainfall Data */}
        <ChartCard title="Weekly Rainfall (mm)">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={rainfallData}
              margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#374151"
                vertical={false}
              />
              <XAxis dataKey="day" stroke="#9CA3AF" />
              <YAxis stroke="#9CA3AF" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1F2937",
                  borderColor: "#374151",
                  color: "#F3F4F6",
                }}
              />
              <Bar dataKey="mm" fill="#3b82f6" radius={[4, 4, 0, 0]} name="Precipitation" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
};

export default FarmChartsPage;
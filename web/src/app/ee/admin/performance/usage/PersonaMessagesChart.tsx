import SvgSimpleLoader from "@opal/icons/simple-loader";
import {
  getDatesList,
  usePersonaMessages,
  usePersonaUniqueUsers,
} from "../lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { InputSelect, Text } from "@opal/components";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import { useState, useMemo } from "react";
import { Agent } from "@/lib/agents/types";

export function PersonaMessagesChart({
  availablePersonas,
  timeRange,
}: {
  availablePersonas: Agent[];
  timeRange: DateRangePickerValue;
}) {
  const [selectedPersonaId, setSelectedPersonaId] = useState<
    number | undefined
  >(undefined);
  const [searchQuery, setSearchQuery] = useState("");

  const {
    data: personaMessagesData,
    isLoading: isPersonaMessagesLoading,
    error: personaMessagesError,
  } = usePersonaMessages(selectedPersonaId, timeRange);

  const {
    data: personaUniqueUsersData,
    isLoading: isPersonaUniqueUsersLoading,
    error: personaUniqueUsersError,
  } = usePersonaUniqueUsers(selectedPersonaId, timeRange);

  const isLoading = isPersonaMessagesLoading || isPersonaUniqueUsersLoading;
  const hasError = personaMessagesError || personaUniqueUsersError;

  const filteredPersonaList = useMemo(() => {
    if (!availablePersonas) return [];
    return availablePersonas.filter((persona) =>
      persona.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [availablePersonas, searchQuery]);

  const chartData = useMemo(() => {
    if (
      !personaMessagesData?.length ||
      !personaUniqueUsersData?.length ||
      selectedPersonaId === undefined
    ) {
      return null;
    }

    const initialDate =
      timeRange.from ||
      new Date(
        Math.min(
          ...personaMessagesData.map((entry) => new Date(entry.date).getTime())
        )
      );
    const dateRange = getDatesList(initialDate);

    // Create maps for messages and unique users data
    const messagesMap = new Map(
      personaMessagesData.map((entry) => [entry.date, entry])
    );
    const uniqueUsersMap = new Map(
      personaUniqueUsersData.map((entry) => [entry.date, entry])
    );

    return dateRange.map((dateStr) => {
      const messageData = messagesMap.get(dateStr);
      const uniqueUserData = uniqueUsersMap.get(dateStr);
      return {
        Day: dateStr,
        Messages: messageData?.total_messages || 0,
        "Unique Users": uniqueUserData?.unique_users || 0,
      };
    });
  }, [
    personaMessagesData,
    personaUniqueUsersData,
    timeRange.from,
    selectedPersonaId,
  ]);

  let content;
  if (isLoading) {
    content = (
      <div className="h-80 flex flex-col items-center justify-center">
        <SvgSimpleLoader className="h-6 w-6" />
      </div>
    );
  } else if (!availablePersonas || hasError) {
    content = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">Failed to fetch data...</p>
      </div>
    );
  } else if (selectedPersonaId === undefined) {
    content = (
      <div className="h-80 text-text-500 flex flex-col">
        <p className="m-auto">Select an agent to view analytics</p>
      </div>
    );
  } else if (!personaMessagesData?.length) {
    content = (
      <div className="h-80 text-text-500 flex flex-col">
        <p className="m-auto">
          No data found for selected agent in the specified time range
        </p>
      </div>
    );
  } else if (chartData) {
    content = (
      <AreaChartDisplay
        className="mt-4"
        data={chartData}
        categories={["Messages", "Unique Users"]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>Agent Analytics</Title>
      <div className="flex flex-col gap-4">
        <Text as="p">
          Messages and unique users per day for the selected agent
        </Text>
        <div className="flex items-center gap-4">
          <div className="w-full max-w-xs">
            <InputSelect
              value={selectedPersonaId?.toString() ?? ""}
              onValueChange={(value) => {
                setSelectedPersonaId(parseInt(value));
              }}
              onOpenChange={(open) => {
                if (open) setSearchQuery("");
              }}
            >
              <InputSelect.Trigger placeholder="Select an agent to display" />
              <InputSelect.Content>
                <InputSelect.Search
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search agents..."
                />
                {filteredPersonaList.map((persona) => (
                  <InputSelect.Item
                    key={persona.id}
                    value={persona.id.toString()}
                  >
                    {persona.name}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </div>
        </div>
      </div>
      {content}
    </CardSection>
  );
}

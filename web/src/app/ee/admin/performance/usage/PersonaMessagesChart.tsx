import { ThreeDotsLoader } from "@/components/Loading";
import { X, Search } from "lucide-react";
import {
  getDatesList,
  usePersonaMessages,
  usePersonaUniqueUsers,
} from "../lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useState, useMemo, useEffect } from "react";
import { Persona } from "@/app/admin/assistants/interfaces";

export function PersonaMessagesChart({
  availablePersonas,
  timeRange,
}: {
  availablePersonas: Persona[];
  timeRange: DateRangePickerValue;
}) {
  const [selectedPersonaId, setSelectedPersonaId] = useState<
    number | undefined
  >(undefined);
  const [searchQuery, setSearchQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(-1);

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < filteredPersonaList.length - 1 ? prev + 1 : prev
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        if (
          highlightedIndex >= 0 &&
          highlightedIndex < filteredPersonaList.length
        ) {
          const filteredPersona = filteredPersonaList[highlightedIndex];
          if (filteredPersona !== undefined) {
            setSelectedPersonaId(filteredPersona.id);
            setSearchQuery("");
            setHighlightedIndex(-1);
          }
        }
        break;
      case "Escape":
        setSearchQuery("");
        setHighlightedIndex(-1);
        break;
    }
  };

  // Reset highlight when search query changes
  useEffect(() => {
    setHighlightedIndex(-1);
  }, [searchQuery]);

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
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
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
        <p className="m-auto">Select an assistant to view analytics</p>
      </div>
    );
  } else if (!personaMessagesData?.length) {
    content = (
      <div className="h-80 text-text-500 flex flex-col">
        <p className="m-auto">
          No data found for selected assistant in the specified time range
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
      <Title>Assistant Analytics</Title>
      <div className="flex flex-col gap-4">
        <Text>
          Messages and unique users per day for the selected assistant
        </Text>
        <div className="flex items-center gap-4">
          <Select
            value={selectedPersonaId?.toString() ?? ""}
            onValueChange={(value) => {
              setSelectedPersonaId(parseInt(value));
            }}
          >
            <SelectTrigger className="flex w-full max-w-xs">
              <SelectValue placeholder="Select an assistant to display" />
            </SelectTrigger>
            <SelectContent>
              <div className="flex items-center px-2 pb-2 sticky top-0 bg-background border-b">
                <Search className="h-4 w-4 mr-2 shrink-0 opacity-50" />
                <input
                  className="flex h-8 w-full rounded-sm bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  placeholder="Search assistants..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onMouseDown={(e) => e.stopPropagation()}
                  onKeyDown={handleKeyDown}
                />
                {searchQuery && (
                  <X
                    className="h-4 w-4 shrink-0 opacity-50 cursor-pointer hover:opacity-100"
                    onClick={() => {
                      setSearchQuery("");
                      setHighlightedIndex(-1);
                    }}
                  />
                )}
              </div>
              {filteredPersonaList.map((persona, index) => (
                <SelectItem
                  key={persona.id}
                  value={persona.id.toString()}
                  className={`${highlightedIndex === index ? "hover" : ""}`}
                  onMouseEnter={() => setHighlightedIndex(index)}
                >
                  {persona.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {content}
    </CardSection>
  );
}

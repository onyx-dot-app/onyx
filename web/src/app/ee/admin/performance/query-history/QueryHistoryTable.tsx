import { useQueryHistory } from "../lib";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import Text from "@/components/ui/text";

import {
  Select,
  SelectItem,
  SelectValue,
  SelectTrigger,
  SelectContent,
} from "@/components/ui/select";
import { ThreeDotsLoader } from "@/components/Loading";
import { ChatSessionMinimal } from "../usage/types";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { FiFrown, FiMinus, FiSmile } from "react-icons/fi";
import { useState } from "react";
import { Feedback } from "@/lib/types";
import { DateRangeSelector } from "../DateRangeSelector";
import { PageSelector } from "@/components/PageSelector";
import Link from "next/link";
import { FeedbackBadge } from "./FeedbackBadge";
import { DownloadAsCSV } from "./DownloadAsCSV";
import CardSection from "@/components/admin/CardSection";

const NUM_IN_PAGE = 20;

function QueryHistoryTableRow({
  chatSessionMinimal,
}: {
  chatSessionMinimal: ChatSessionMinimal;
}) {
  return (
    <TableRow
      key={chatSessionMinimal.id}
      className="hover:bg-hover-light cursor-pointer relative"
    >
      <TableCell>
        <Text className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_user_message || "-"}
        </Text>
      </TableCell>
      <TableCell>
        <Text className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_ai_message || "-"}
        </Text>
      </TableCell>
      <TableCell>
        <FeedbackBadge feedback={chatSessionMinimal.feedback_type} />
      </TableCell>
      <TableCell>{chatSessionMinimal.user_email || "-"}</TableCell>
      <TableCell>{chatSessionMinimal.persona_name || "Unknown"}</TableCell>
      <TableCell>
        {timestampToReadableDate(chatSessionMinimal.time_created)}
      </TableCell>
      {/* Wrapping in <td> to avoid console warnings */}
      <td className="w-0 p-0">
        <Link
          href={`/admin/performance/query-history/${chatSessionMinimal.id}`}
          className="absolute w-full h-full left-0"
        ></Link>
      </td>
    </TableRow>
  );
}

function SelectFeedbackType({
  value,
  onValueChange,
}: {
  value: Feedback | "all";
  onValueChange: (value: Feedback | "all") => void;
}) {
  return (
    <div>
      <Text className="my-auto mr-2 font-medium mb-1">Feedback Type</Text>
      <div className="max-w-sm space-y-6">
        <Select
          value={value}
          onValueChange={onValueChange as (value: string) => void}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select feedback type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              <div className="flex items-center gap-2">
                <FiMinus className="h-4 w-4" />
                <span>Any</span>
              </div>
            </SelectItem>
            <SelectItem value="like">
              <div className="flex items-center gap-2">
                <FiSmile className="h-4 w-4" />
                <span>Like</span>
              </div>
            </SelectItem>
            <SelectItem value="dislike">
              <div className="flex items-center gap-2">
                <FiFrown className="h-4 w-4" />
                <span>Dislike</span>
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export function QueryHistoryTable() {
  const {
    data: chatSessionData,
    selectedFeedbackType,
    setSelectedFeedbackType,
    timeRange,
    setTimeRange,
  } = useQueryHistory();

  const [page, setPage] = useState(1);

  return (
    <CardSection className="mt-8">
      {chatSessionData ? (
        <>
          <div className="flex">
            <div className="gap-y-3 flex flex-col">
              <SelectFeedbackType
                value={selectedFeedbackType || "all"}
                onValueChange={setSelectedFeedbackType}
              />

              <DateRangeSelector
                value={timeRange}
                onValueChange={(value) => {
                  if (value) {
                    setTimeRange({
                      ...value,
                      selectValue: timeRange.selectValue,
                    });
                  }
                }}
              />
            </div>

            <DownloadAsCSV />
          </div>
          <Separator />
          <Table className="mt-5">
            <TableHeader>
              <TableRow>
                <TableHead>First User Message</TableHead>
                <TableHead>First AI Response</TableHead>
                <TableHead>Feedback</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Persona</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {chatSessionData
                .slice(NUM_IN_PAGE * (page - 1), NUM_IN_PAGE * page)
                .map((chatSessionMinimal) => (
                  <QueryHistoryTableRow
                    key={chatSessionMinimal.id}
                    chatSessionMinimal={chatSessionMinimal}
                  />
                ))}
            </TableBody>
          </Table>

          <div className="mt-3 flex">
            <div className="mx-auto">
              <PageSelector
                totalPages={Math.ceil(chatSessionData.length / NUM_IN_PAGE)}
                currentPage={page}
                onPageChange={(newPage) => {
                  setPage(newPage);
                  window.scrollTo({
                    top: 0,
                    left: 0,
                    behavior: "smooth",
                  });
                }}
              />
            </div>
          </div>
        </>
      ) : (
        <div className="h-80 flex flex-col">
          <ThreeDotsLoader />
        </div>
      )}
    </CardSection>
  );
}

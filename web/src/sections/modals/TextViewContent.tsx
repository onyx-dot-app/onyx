"use client";

import { useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import Text from "@/refresh-components/texts/Text";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { cn } from "@/lib/utils";

interface TextViewContentProps {
  fileContent: string;
  fileType: string;
}

export default function TextViewContent({
  fileContent,
  fileType,
}: TextViewContentProps) {
  const csvData = useMemo(() => {
    if (!fileType.startsWith("text/csv")) {
      return null;
    }

    const lines = fileContent.split(/\r?\n/).filter((l) => l.length > 0);
    const headers = lines.length > 0 ? lines[0]?.split(",") ?? [] : [];
    const rows = lines.slice(1).map((line) => line.split(","));

    return { headers, rows } as { headers: string[]; rows: string[][] };
  }, [fileContent, fileType]);

  return (
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
      {csvData ? (
        <Table>
          <TableHeader className="sticky top-0 z-sticky">
            <TableRow className="bg-background-tint-02">
              {csvData.headers.map((h, i) => (
                <TableHead key={i}>
                  <Text
                    as="p"
                    className="line-clamp-2 font-medium"
                    text03
                    mainUiBody
                  >
                    {h}
                  </Text>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {csvData.rows.map((row, rIdx) => (
              <TableRow key={rIdx}>
                {csvData.headers.map((_, cIdx) => (
                  <TableCell
                    key={cIdx}
                    className={cn(
                      cIdx === 0 && "sticky left-0 bg-background-tint-01",
                      "py-0 px-4 whitespace-normal break-words"
                    )}
                  >
                    {row?.[cIdx] ?? ""}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <MinimalMarkdown
          content={fileContent}
          className="w-full pb-4 h-full text-lg break-words"
        />
      )}
    </ScrollIndicatorDiv>
  );
}

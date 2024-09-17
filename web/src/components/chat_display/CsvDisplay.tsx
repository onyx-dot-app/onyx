import React, { useEffect, useState } from "react";

import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import { Modal } from "@/components/Modal";
import {
  DexpandTwoIcon,
  DownloadCSVIcon,
  ExpandTwoIcon,
  OpenIcon,
} from "@/components/icons/icons";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { FileDescriptor } from "@/app/chat/interfaces";
import { WarningCircle } from "@phosphor-icons/react";

export default function CsvPage({
  fileDescriptor,
  close,
}: {
  fileDescriptor: FileDescriptor;
  close: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const expand = () => {
    setExpanded((expanded) => !expanded);
  };

  return (
    <>
      {expanded ? (
        <Modal
          hideCloseButton
          onOutsideClick={() => setExpanded(false)}
          className="!max-w-5xl overflow-hidden rounded-lg animate-all ease-in !p-0"
        >
          <CsvSection
            close={close}
            expanded={expanded}
            expand={expand}
            fileDescriptor={fileDescriptor}
          />
        </Modal>
      ) : (
        <CsvSection
          close={close}
          expanded={expanded}
          expand={expand}
          fileDescriptor={fileDescriptor}
        />
      )}
    </>
  );
}

export interface InteractiveToolResult {
  fileDescriptor: FileDescriptor;
  expanded: boolean;
  expand: () => void;
  close: () => void;
}

export const CsvSection = ({
  fileDescriptor,
  expanded,
  expand,
  close,
}: InteractiveToolResult) => {
  interface CSVData {
    [key: string]: string;
  }
  const [data, setData] = useState<CSVData[]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fadeIn, setFadeIn] = useState(false);

  const fileId = fileDescriptor.id;
  useEffect(() => {
    fetchCSV(fileId);
  }, []);

  const fetchCSV = async (id: string) => {
    setIsLoading(true);
    try {
      const response = await fetch(`api/chat/file/${id}`);
      if (!response.ok) {
        throw new Error("Failed to fetch CSV file");
      }
      const csvData = await response.text();
      const rows = csvData.trim().split("\n");
      const parsedHeaders = rows[0].split(",");
      setHeaders(parsedHeaders);

      const parsedData: CSVData[] = rows.slice(1).map((row) => {
        const values = row.split(",");
        return parsedHeaders.reduce<CSVData>((obj, header, index) => {
          obj[header] = values[index];
          return obj;
        }, {});
      });
      setData(parsedData);
    } catch (error) {
      console.error("Error fetching CSV file:", error);
    } finally {
      // Add a slight delay before setting isLoading to false
      setTimeout(() => setIsLoading(false), 300);
    }
  };

  useEffect(() => {
    if (!isLoading) {
      // Trigger fade-in effect after a short delay
      setTimeout(() => setFadeIn(true), 50);
    } else {
      setFadeIn(false);
    }
  }, [isLoading]);

  const downloadFile = () => {
    if (!fileId) return;

    const csvContent = [headers.join(",")]
      .concat(data.map((row) => headers.map((header) => row[header]).join(",")))
      .join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    if (link.download !== undefined) {
      const url = URL.createObjectURL(blob);
      link.setAttribute("href", url);
      link.setAttribute("download", `${fileDescriptor.name || "download"}.csv`);
      link.style.visibility = "hidden";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  return (
    <div
      className={`${!expanded ? "w-message-sm" : "w-full"} !rounded !rounded-lg overflow-y-hidden w-full border border-border`}
    >
      <CardHeader className="w-full !py-0  !pb-4 border-b border-border border-b-neutral-200 !pt-4 !mb-0 z-[10] top-0">
        <div className="flex justify-between items-center">
          <CardTitle className="!my-auto text-ellipsis line-clamp-1 text-xl font-semibold text-text-700 pr-4 transition-colors duration-300">
            {fileDescriptor.name}
          </CardTitle>
          <div className="flex !my-auto">
            <TooltipGroup gap="gap-x-4">
              <CustomTooltip showTick line content="Download file">
                <button onClick={() => downloadFile()}>
                  <DownloadCSVIcon className="cursor-pointer transition-colors duration-300 hover:text-text-800 h-6 w-6 text-text-400" />
                </button>
              </CustomTooltip>
              <CustomTooltip
                line
                showTick
                content={expanded ? "Minimize" : "Full screen"}
              >
                <button onClick={() => expand()}>
                  {!expanded ? (
                    <ExpandTwoIcon className="transition-colors duration-300 hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                  ) : (
                    <DexpandTwoIcon className="transition-colors duration-300 hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                  )}
                </button>
              </CustomTooltip>
              <CustomTooltip showTick line content="Hide">
                <button onClick={() => close()}>
                  <OpenIcon className="transition-colors duration-300 hover:text-text-800 h-6 w-6 cursor-pointer text-text-400" />
                </button>
              </CustomTooltip>
            </TooltipGroup>
          </div>
        </div>
      </CardHeader>
      <Card className="!rounded-none w-full max-h-[600px] !p-0 relative overflow-x-scroll overflow-y-scroll mx-auto">
        <CardContent className="!p-0">
          {isLoading ? (
            <div
              className={`flex items-center justify-center ${expanded ? "h-[500px]" : "h-[300px]"}`}
            >
              <div className="animate-pulse w- flex space-x-4">
                <div className="rounded-full bg-background-200 h-10 w-10"></div>
                <div className="w-full flex-1 space-y-4 py-1">
                  <div className="h-2 w-full bg-background-200 rounded"></div>
                  <div className="w-full space-y-3">
                    <div className="grid grid-cols-3 gap-4">
                      <div className="h-2 bg-background-200 rounded col-span-2"></div>
                      <div className="h-2 bg-background-200 rounded col-span-1"></div>
                    </div>
                    <div className="h-2 bg-background-200 rounded"></div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div
              className={`transition-opacity transform duration-1000 ease-in-out ${
                fadeIn ? "opacity-100" : "opacity-0"
              }`}
            >
              <Table>
                <TableHeader className="!sticky !top-0 ">
                  <TableRow className="!bg-neutral-100">
                    {headers.map((header, index) => (
                      <TableHead className="!sticky !top-0 " key={index}>
                        <p className="text-text-600 line-clamp-2 my-2 font-medium">
                          {index == 0 ? "" : header}
                        </p>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>

                <TableBody className="max-h-[300px] overflow-y-auto">
                  {data.length > 0 ? (
                    data.map((row, rowIndex) => (
                      <TableRow key={rowIndex}>
                        {headers.map((header, cellIndex) => (
                          <TableCell
                            className={`${cellIndex == 0 && "sticky left-0 !bg-neutral-100"}`}
                            key={cellIndex}
                          >
                            {row[header]}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={headers.length}
                        className="text-center py-8"
                      >
                        <div className="flex flex-col items-center justify-center space-y-2">
                          <WarningCircle className="w-8 h-8 text-error" />
                          <p className="text-text-600 font-medium">
                            No data available
                          </p>
                          <p className="text-text-400 text-sm">
                            The CSV file appears to be empty or couldn&apos;t be
                            loaded properly.
                          </p>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

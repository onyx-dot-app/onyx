// CsvContent
import React, { useState, useEffect } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ContentComponentProps } from "./ExpandableContentWrapper";
import { WarningCircle } from "@phosphor-icons/react";

const CsvContent: React.FC<ContentComponentProps> = ({
  fileDescriptor,
  isLoading,
  fadeIn,
  expanded = false,
}) => {
  const [data, setData] = useState<Record<string, string>[]>([]);
  const [headers, setHeaders] = useState<string[]>([]);

  useEffect(() => {
    fetchCSV(fileDescriptor.id);
  }, [fileDescriptor.id]);

  const fetchCSV = async (id: string) => {
    try {
      const response = await fetch(`api/chat/file/${id}`);
      if (!response.ok) {
        throw new Error("Failed to fetch CSV file");
      }

      const contentLength = response.headers.get("Content-Length");
      const fileSizeInMB = contentLength
        ? parseInt(contentLength) / (1024 * 1024)
        : 0;
      const MAX_FILE_SIZE_MB = 5;

      if (fileSizeInMB > MAX_FILE_SIZE_MB) {
        throw new Error("File size exceeds the maximum limit of 5MB");
      }

      const csvData = await response.text();
      const rows = csvData.trim().split("\n");
      const firstRow = rows[0];
      if (!firstRow) {
        throw new Error("CSV file is empty");
      }
      const parsedHeaders = firstRow.split(",");
      setHeaders(parsedHeaders);

      const parsedData: Record<string, string>[] = rows.slice(1).map((row) => {
        const values = row.split(",");
        return parsedHeaders.reduce<Record<string, string>>(
          (obj, header, index) => {
            const val = values[index];
            if (val !== undefined) {
              obj[header] = val;
            }
            return obj;
          },
          {}
        );
      });
      setData(parsedData);
    } catch (error) {
      console.error("Error fetching CSV file:", error);
      setData([]);
      setHeaders([]);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[300px]">
        <div className="animate-pulse flex space-x-4">
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
    );
  }

  return (
    <div
      className={`transition-opacity transform relative duration-1000 ease-in-out ${
        fadeIn ? "opacity-100" : "opacity-0"
      }`}
    >
      <div
        className={`flex relative ${expanded ? "max-h-2/3" : "max-h-[300px]"}`}
      >
        <Table>
          <TableHeader className="sticky z-[1000] top-0">
            <TableRow className="hover:bg-background-125 bg-background-125">
              {headers.map((header, index) => (
                <TableHead key={index}>
                  <p className="text-text-600 line-clamp-2 my-2 font-medium">
                    {header}
                  </p>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>

          <TableBody className="h-[300px] overflow-y-hidden ">
            {data.length > 0 ? (
              data.map((row, rowIndex) => (
                <TableRow key={rowIndex}>
                  {headers.map((header, cellIndex) => (
                    <TableCell
                      className={`${
                        cellIndex === 0 ? "sticky left-0 bg-background-100" : ""
                      }`}
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
                      {headers.length === 0
                        ? "Error loading CSV"
                        : "No data available"}
                    </p>
                    <p className="text-text-400 text-sm">
                      {headers.length === 0
                        ? "The CSV file may be too large or couldn't be loaded properly."
                        : "The CSV file appears to be empty."}
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
};

export default CsvContent;

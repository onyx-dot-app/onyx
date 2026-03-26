"use client";

import { useState, useEffect } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ThreeDotsLoader } from "@/components/Loading";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button, Text } from "@opal/components";
import { Card } from "@/components/ui/card";
import { markdown } from "@opal/utils";
import Spacer from "@/refresh-components/Spacer";
import { Spinner } from "@/components/Spinner";
import { SvgDownloadCloud } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.DEBUG;

function Main() {
  const [categories, setCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const response = await fetch("/api/admin/long-term-logs");
        if (!response.ok) throw new Error("Failed to fetch categories");
        const data = await response.json();
        setCategories(data);
      } catch (error) {
        console.error("Error fetching categories:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchCategories();
  }, []);

  const handleDownload = async (category: string) => {
    setIsDownloading(true);
    try {
      const response = await fetch(
        `/api/admin/long-term-logs/${category}/download`
      );
      if (!response.ok) throw new Error("Failed to download logs");

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);

      const a = document.createElement("a");
      a.href = url;
      a.download = `${category}-logs.zip`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error("Error downloading logs:", error);
    } finally {
      setIsDownloading(false);
    }
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      {isDownloading && <Spinner />}
      <div className="mb-8">
        <Text as="p">
          {markdown(
            "**Debug Logs** provide detailed information about system operations and events. You can download logs for each category to analyze system behavior or troubleshoot issues."
          )}
        </Text>
        <Spacer rem={0.75} />

        {categories.length > 0 && (
          <Card className="mt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Category</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {categories.map((category) => (
                  <TableRow
                    key={category}
                    className="hover:bg-transparent dark:hover:bg-transparent"
                  >
                    <TableCell className="font-medium">{category}</TableCell>
                    <TableCell>
                      <Button
                        prominence="secondary"
                        onClick={() => handleDownload(category)}
                        icon={SvgDownloadCloud}
                      >
                        Download Logs
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

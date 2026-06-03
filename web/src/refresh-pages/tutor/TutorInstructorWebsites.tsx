"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import { SvgGlobe, SvgTrash } from "@opal/icons";
import { ThreeDotsLoader } from "@/components/Loading";
import { CCPairStatus } from "@/components/Status";
import Title from "@/components/ui/title";
import { Card } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ValidStatuses } from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";

// Mirrors the backend `LtiCourseWebsiteSnapshot` shape.
interface LtiCourseWebsiteSnapshot {
  cc_pair_id: number;
  connector_id: number;
  credential_id: number;
  name: string;
  base_url: string;
  crawl_type: string;
  cc_pair_status: ConnectorCredentialPairStatus;
  indexing_status: ValidStatuses | null;
  total_docs_indexed: number;
  has_indexed_documents: boolean;
  last_successful_index_time: string | null;
}

interface TutorInstructorWebsitesProps {
  courseId: string;
}

// Crawl strategies the backend accepts (UPLOAD is intentionally excluded).
const CRAWL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "recursive", label: "Crawl entire site" },
  { value: "single", label: "Single page only" },
  { value: "sitemap", label: "From sitemap.xml" },
];

function crawlTypeLabel(crawlType: string): string {
  return (
    CRAWL_TYPE_OPTIONS.find((option) => option.value === crawlType)?.label ??
    crawlType
  );
}

function getErrorDetail(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

export default function TutorInstructorWebsites({
  courseId,
}: TutorInstructorWebsitesProps) {
  const websitesKey = `/api/auth/lti/course/${encodeURIComponent(
    courseId
  )}/websites`;

  const {
    data: websites,
    isLoading,
    mutate,
  } = useSWR<LtiCourseWebsiteSnapshot[]>(websitesKey, errorHandlingFetcher, {
    refreshInterval: 10_000,
  });

  const [url, setUrl] = useState("");
  const [crawlType, setCrawlType] = useState("recursive");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingCcPairId, setDeletingCcPairId] = useState<number | null>(null);

  const sortedWebsites = useMemo(() => {
    return (websites ?? [])
      .slice()
      .sort((a, b) => a.base_url.localeCompare(b.base_url));
  }, [websites]);

  const handleAdd = useCallback(async () => {
    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      toast.error("Enter a website URL to add.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch(websitesKey, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmedUrl, crawl_type: crawlType }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          getErrorDetail(payload, "Could not add this website. Try again.")
        );
      }
      toast.success("Website added. Indexing has started.");
      setUrl("");
      await mutate();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Could not add this website."
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [crawlType, mutate, url, websitesKey]);

  const handleRemove = useCallback(
    async (ccPairId: number) => {
      setDeletingCcPairId(ccPairId);
      try {
        const response = await fetch(`${websitesKey}/${ccPairId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(
            getErrorDetail(payload, "Could not remove this website.")
          );
        }
        toast.success("Website removal started.");
        await mutate();
      } catch (e) {
        toast.error(
          e instanceof Error ? e.message : "Could not remove this website."
        );
      } finally {
        setDeletingCcPairId(null);
      }
    },
    [mutate, websitesKey]
  );

  return (
    <div className="mt-8">
      <Title className="mb-2" size="md">
        Course Websites
      </Title>
      <Text as="p" secondaryBody text03 className="mb-4">
        Add public web pages for the tutor to use. They are only visible to
        students in this course.
      </Text>

      <Card className="p-4">
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-center"
          onSubmit={(e) => {
            e.preventDefault();
            void handleAdd();
          }}
        >
          <div className="flex-1">
            <InputTypeIn
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/resource"
              autoComplete="off"
              showClearButton={false}
            />
          </div>
          <div className="sm:w-[14rem]">
            <InputSelect value={crawlType} onValueChange={setCrawlType}>
              <InputSelect.Trigger placeholder="Crawl type" />
              <InputSelect.Content>
                {CRAWL_TYPE_OPTIONS.map((option) => (
                  <InputSelect.Item key={option.value} value={option.value}>
                    {option.label}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </div>
          <Button type="submit" icon={SvgGlobe} disabled={isSubmitting}>
            {isSubmitting ? "Adding" : "Add website"}
          </Button>
        </form>
      </Card>

      <div className="mt-4">
        {isLoading ? (
          <div className="flex w-full items-center justify-center py-8">
            <ThreeDotsLoader />
          </div>
        ) : sortedWebsites.length === 0 ? (
          <Callout type="notice" title="No websites added yet">
            Add a public URL above to give the tutor extra knowledge for this
            course.
          </Callout>
        ) : (
          <Card className="overflow-hidden p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Website</TableHead>
                  <TableHead>Crawl Type</TableHead>
                  <TableHead>Documents</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedWebsites.map((website) => (
                  <TableRow key={website.cc_pair_id} className="border-border">
                    <TableCell className="max-w-[20rem] truncate">
                      {website.base_url}
                    </TableCell>
                    <TableCell>{crawlTypeLabel(website.crawl_type)}</TableCell>
                    <TableCell>
                      {website.total_docs_indexed.toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <CCPairStatus
                        ccPairStatus={website.cc_pair_status}
                        inRepeatedErrorState={false}
                        lastIndexAttemptStatus={website.indexing_status}
                      />
                    </TableCell>
                    <TableCell>
                      <Button
                        prominence="tertiary"
                        variant="danger"
                        size="sm"
                        icon={SvgTrash}
                        disabled={deletingCcPairId === website.cc_pair_id}
                        onClick={() => void handleRemove(website.cc_pair_id)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}

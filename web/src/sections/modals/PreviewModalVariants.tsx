import React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgDownload, SvgZoomIn, SvgZoomOut } from "@opal/icons";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { cn } from "@/lib/utils";
import { Section } from "@/layouts/general-layouts";
import { getCodeLanguage } from "@/lib/languages";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { extractCodeText } from "@/app/app/message/codeUtils";

export interface PreviewContext {
  fileContent: string;
  fileUrl: string;
  fileName: string;
  language: string;
  lineCount: number;
  fileSize: string;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
}

export interface PreviewVariant {
  /** Return true if this variant should handle the given file. */
  matches: (semanticIdentifier: string | null, mimeType: string) => boolean;
  /** Modal width. */
  width: "lg" | "md" | "md-sm" | "sm";
  /** Modal height. */
  height: "fit" | "sm" | "lg" | "full";
  /** Whether the fetcher should read the blob as text. */
  needsTextContent: boolean;
  /** String shown below the title in the modal header. */
  headerDescription: (ctx: PreviewContext) => string;
  /** Body content. */
  renderContent: (ctx: PreviewContext) => React.ReactNode;
  /** Left side of the floating footer (e.g. line count text, zoom controls). Return null for nothing. */
  renderFooterLeft: (ctx: PreviewContext) => React.ReactNode;
  /** Right side of the floating footer (e.g. copy + download buttons). */
  renderFooterRight: (ctx: PreviewContext) => React.ReactNode;
}

interface DownloadButtonProps {
  fileUrl: string;
  fileName: string;
}
function DownloadButton({ fileUrl, fileName }: DownloadButtonProps) {
  return (
    <a href={fileUrl} download={fileName}>
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgDownload}
        tooltip="Download"
      />
    </a>
  );
}

interface CopyButtonProps {
  getText: () => string;
}
function CopyButton({ getText }: CopyButtonProps) {
  return (
    <CopyIconButton getCopyText={getText} tooltip="Copy content" size="sm" />
  );
}

function ZoomControls({
  zoom,
  onZoomIn,
  onZoomOut,
}: {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
}) {
  return (
    <div className="rounded-12 bg-background-tint-00 p-1 shadow-lg">
      <Section flexDirection="row" width="fit">
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgZoomOut}
          onClick={onZoomOut}
          tooltip="Zoom Out"
        />
        <Text mainUiMono text03>
          {zoom}%
        </Text>
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgZoomIn}
          onClick={onZoomIn}
          tooltip="Zoom In"
        />
      </Section>
    </div>
  );
}

const MARKDOWN_MIMES = [
  "text/markdown",
  "text/x-markdown",
  "text/plain",
  "text/x-rst",
  "text/x-org",
];

const codeVariant: PreviewVariant = {
  matches: (name) => !!getCodeLanguage(name || ""),
  width: "md",
  height: "lg",
  needsTextContent: true,

  headerDescription: (ctx) =>
    ctx.fileContent
      ? `${ctx.language} - ${ctx.lineCount} ${
          ctx.lineCount === 1 ? "line" : "lines"
        } · ${ctx.fileSize}`
      : "",

  renderContent: (ctx) => (
    <MinimalMarkdown
      content={`\`\`\`${ctx.language}\n${ctx.fileContent}\n\n\`\`\``}
      className="w-full break-words h-full"
      components={{
        code: ({ node, children }: any) => {
          const codeText = extractCodeText(node, ctx.fileContent, children);
          return (
            <CodeBlock className="" codeText={codeText}>
              {children}
            </CodeBlock>
          );
        },
      }}
    />
  ),

  renderFooterLeft: (ctx) => (
    <Text text03 mainUiBody className="select-none">
      {ctx.lineCount} {ctx.lineCount === 1 ? "line" : "lines"}
    </Text>
  ),

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};

const imageVariant: PreviewVariant = {
  matches: (_name, mime) => mime.startsWith("image/"),
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <div
      className="flex flex-1 min-h-0 items-center justify-center p-4 transition-transform duration-300 ease-in-out"
      style={{
        transform: `scale(${ctx.zoom / 100})`,
        transformOrigin: "center",
      }}
    >
      <img
        src={ctx.fileUrl}
        alt={ctx.fileName}
        className="max-w-full max-h-full object-contain"
      />
    </div>
  ),

  renderFooterLeft: (ctx) => (
    <ZoomControls
      zoom={ctx.zoom}
      onZoomIn={ctx.onZoomIn}
      onZoomOut={ctx.onZoomOut}
    />
  ),

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};

const pdfVariant: PreviewVariant = {
  matches: (_name, mime) => mime === "application/pdf",
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <iframe
      src={`${ctx.fileUrl}#toolbar=0`}
      className="w-full h-full flex-1 min-h-0 border-none"
      title="PDF Viewer"
    />
  ),

  renderFooterLeft: () => null,
  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};

interface CsvData {
  headers: string[];
  rows: string[][];
}

function parseCsv(content: string): CsvData {
  const lines = content.split(/\r?\n/).filter((l) => l.length > 0);
  const headers = lines.length > 0 ? lines[0]?.split(",") ?? [] : [];
  const rows = lines.slice(1).map((line) => line.split(","));
  return { headers, rows };
}

const csvVariant: PreviewVariant = {
  matches: (name, mime) =>
    mime.startsWith("text/csv") || (name || "").toLowerCase().endsWith(".csv"),
  width: "lg",
  height: "full",
  needsTextContent: true,
  headerDescription: (ctx) => {
    if (!ctx.fileContent) return "";
    const { rows } = parseCsv(ctx.fileContent);
    return `CSV - ${rows.length} rows · ${ctx.fileSize}`;
  },

  renderContent: (ctx) => {
    if (!ctx.fileContent) return null;
    const { headers, rows } = parseCsv(ctx.fileContent);
    return (
      <Section justifyContent="start" alignItems="start" padding={1}>
        <Table>
          <TableHeader className="sticky top-0 z-sticky">
            <TableRow className="bg-background-tint-02">
              {headers.map((h: string, i: number) => (
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
            {rows.map((row: string[], rIdx: number) => (
              <TableRow key={rIdx}>
                {headers.map((_: string, cIdx: number) => (
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
      </Section>
    );
  },

  renderFooterLeft: (ctx) => {
    if (!ctx.fileContent) return null;
    const { headers, rows } = parseCsv(ctx.fileContent);
    return (
      <Text text03 mainUiBody className="select-none">
        {headers.length} {headers.length === 1 ? "column" : "columns"} ·{" "}
        {rows.length} {rows.length === 1 ? "row" : "rows"}
      </Text>
    );
  },
  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};

const markdownVariant: PreviewVariant = {
  matches: (name, mime) => {
    if (MARKDOWN_MIMES.some((m) => mime.startsWith(m))) return true;
    const lower = (name || "").toLowerCase();
    return (
      lower.endsWith(".md") ||
      lower.endsWith(".markdown") ||
      lower.endsWith(".txt") ||
      lower.endsWith(".rst") ||
      lower.endsWith(".org")
    );
  },
  width: "lg",
  height: "full",
  needsTextContent: true,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
      <MinimalMarkdown
        content={ctx.fileContent}
        className="w-full pb-4 h-full text-lg break-words"
      />
    </ScrollIndicatorDiv>
  ),

  renderFooterLeft: () => null,

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};

const unsupportedVariant: PreviewVariant = {
  matches: () => true,
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <div className="flex flex-col items-center justify-center flex-1 min-h-0 gap-4 p-6">
      <Text as="p" text03 mainUiBody>
        This file format is not supported for preview.
      </Text>
      <a href={ctx.fileUrl} download={ctx.fileName}>
        <Button>Download File</Button>
      </a>
    </div>
  ),

  renderFooterLeft: () => null,
  renderFooterRight: (ctx) => (
    <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
  ),
};

const PREVIEW_VARIANTS: PreviewVariant[] = [
  codeVariant,
  imageVariant,
  pdfVariant,
  csvVariant,
  markdownVariant,
];

export function resolveVariant(
  semanticIdentifier: string | null,
  mimeType: string
): PreviewVariant {
  return (
    PREVIEW_VARIANTS.find((v) => v.matches(semanticIdentifier, mimeType)) ??
    unsupportedVariant
  );
}

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";
import TextSeparator from "@/refresh-components/TextSeparator";

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

export const csvVariant: PreviewVariant = {
  matches: (name, mime) =>
    mime.startsWith("text/csv") || (name || "").toLowerCase().endsWith(".csv"),
  width: "lg",
  height: "full",
  needsTextContent: true,
  headerDescription: (ctx) => {
    if (!ctx.fileContent) return "";
    const { rows } = parseCsv(ctx.fileContent);
    return `CSV - ${rows.length} rows • ${ctx.fileSize}`;
  },

  renderContent: (ctx) => {
    if (!ctx.fileContent) return null;
    const { headers, rows } = parseCsv(ctx.fileContent);
    return (
      <Section justifyContent="start" alignItems="start" padding={1}>
        <Table>
          <TableHeader className="sticky top-0 z-sticky">
            <TableRow noHover>
              {headers.map((h: string, i: number) => (
                <TableHead key={i}>
                  <Text as="p" className="line-clamp-2" text04 secondaryAction>
                    {h}
                  </Text>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row: string[], rIdx: number) => (
              <TableRow key={rIdx} noHover>
                {headers.map((_: string, cIdx: number) => (
                  <TableCell
                    key={cIdx}
                    className={cn(
                      cIdx === 0 && "sticky left-0",
                      "py-4 px-4 whitespace-normal break-words"
                    )}
                  >
                    <Text
                      as="p"
                      {...(cIdx === 0
                        ? { text04: true, secondaryAction: true }
                        : { text03: true, secondaryBody: true })}
                    >
                      {row?.[cIdx] ?? ""}
                    </Text>
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <TextSeparator
          count={rows.length}
          text={rows.length === 1 ? "row" : "rows"}
        />
      </Section>
    );
  },

  renderFooterLeft: (ctx) => {
    if (!ctx.fileContent) return null;
    const { headers, rows } = parseCsv(ctx.fileContent);
    return (
      <Text text03 mainUiBody className="select-none">
        {headers.length} {headers.length === 1 ? "column" : "columns"} •{" "}
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

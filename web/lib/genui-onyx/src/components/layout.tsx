import React from "react";
import { z } from "zod";
import { defineComponent } from "@onyx/genui";
import { cn } from "@/lib/utils";

const gapMap: Record<string, string> = {
  none: "gap-0",
  xs: "gap-1",
  sm: "gap-2",
  md: "gap-4",
  lg: "gap-6",
  xl: "gap-8",
};

const alignMap: Record<string, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
};

const gapSchema = z
  .enum(["none", "xs", "sm", "md", "lg", "xl"])
  .optional()
  .describe("Gap between children");

const alignSchema = z
  .enum(["start", "center", "end", "stretch"])
  .optional()
  .describe("Cross-axis alignment");

export const stackComponent = defineComponent({
  name: "Stack",
  description: "Vertical stack layout — arranges children top to bottom",
  group: "Layout",
  props: z.object({
    children: z.array(z.unknown()).optional().describe("Child elements"),
    gap: gapSchema,
    align: alignSchema,
  }),
  component: ({
    props,
  }: {
    props: { children?: React.ReactNode[]; gap?: string; align?: string };
  }) => (
    <div
      className={cn(
        "flex flex-col",
        gapMap[props.gap ?? "sm"],
        props.align && alignMap[props.align]
      )}
    >
      {props.children}
    </div>
  ),
});

export const rowComponent = defineComponent({
  name: "Row",
  description: "Horizontal row layout — arranges children left to right",
  group: "Layout",
  props: z.object({
    children: z.array(z.unknown()).optional().describe("Child elements"),
    gap: gapSchema,
    align: alignSchema,
    wrap: z.boolean().optional().describe("Allow wrapping to next line"),
  }),
  component: ({
    props,
  }: {
    props: {
      children?: React.ReactNode[];
      gap?: string;
      align?: string;
      wrap?: boolean;
    };
  }) => (
    <div
      className={cn(
        "flex flex-row",
        gapMap[props.gap ?? "sm"],
        props.align && alignMap[props.align],
        props.wrap && "flex-wrap"
      )}
    >
      {props.children}
    </div>
  ),
});

export const columnComponent = defineComponent({
  name: "Column",
  description: "A column within a Row, with optional width control",
  group: "Layout",
  props: z.object({
    children: z.array(z.unknown()).optional().describe("Child elements"),
    width: z
      .string()
      .optional()
      .describe("CSS width (e.g. '50%', '200px', 'auto')"),
  }),
  component: ({
    props,
  }: {
    props: { children?: React.ReactNode[]; width?: string };
  }) => (
    <div
      className="flex flex-col"
      style={props.width ? { width: props.width } : undefined}
    >
      {props.children}
    </div>
  ),
});

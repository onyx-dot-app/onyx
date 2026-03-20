"use client";

import { createContext, useContext } from "react";
import type { SizeVariants } from "@opal/types";

type TableSize = Extract<SizeVariants, "md" | "lg">;

const TableSizeContext = createContext<TableSize>("lg");

interface TableSizeProviderProps {
  size: TableSize;
  children: React.ReactNode;
}

function TableSizeProvider({ size, children }: TableSizeProviderProps) {
  return (
    <TableSizeContext.Provider value={size}>
      {children}
    </TableSizeContext.Provider>
  );
}

function useTableSize(): TableSize {
  return useContext(TableSizeContext);
}

export { TableSizeProvider, useTableSize };
export type { TableSize };

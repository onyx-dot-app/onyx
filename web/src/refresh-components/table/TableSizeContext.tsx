"use client";

import { createContext, useContext } from "react";

type TableSize = "regular" | "small";

const TableSizeContext = createContext<TableSize>("regular");

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

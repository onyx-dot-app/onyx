"use client";

import { createContext, useContext } from "react";
/** A body row's height in rem: `2.75` is 44px, `2.25` is 36px. */
type TableSize = 2.25 | 2.75;

const TableSizeContext = createContext<TableSize>(2.75);

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

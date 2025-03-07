import React, { FC } from "react";

type Column = {
  header: string;
  key: string;
  width?: number | string;
  alignment?: "left" | "right";
};

type TableData = {
  [key: string]: string | number | JSX.Element;
};

interface BasicTableProps {
  columns: Column[];
  data: TableData[];
  onSelect?: (row: TableData) => void;
}

export const BasicTable: FC<BasicTableProps> = ({
  columns,
  data,
  onSelect,
}) => {
  return (
    <div>
      <table className="w-full table-auto">
        <thead>
          <tr className="text-left bg-background-700">
            {columns.map((column, index) => {
              const isRightAligned = column?.alignment === "right";
              return (
                <th
                  key={index}
                  className={
                    (column.width ? `w-${column.width} ` : "") +
                    "px-4 py-2 font-bold" +
                    (index === 0 ? " rounded-tl-sm" : "") +
                    (index === columns.length - 1 ? " rounded-tr-sm" : "")
                  }
                >
                  <div
                    className={isRightAligned ? "flex flex-row-reverse" : ""}
                  >
                    {column.header}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIndex) => (
            <tr
              key={rowIndex}
              className={
                "text-sm" +
                (onSelect ? " hover:bg-background-800 cursor-pointer" : "")
              }
              onClick={() => onSelect && onSelect(row)}
            >
              {columns.map((column, colIndex) => {
                const isRightAligned = column?.alignment === "right";
                return (
                  <td
                    key={colIndex}
                    className={
                      (column.width ? `w-${column.width} ` : "") +
                      (isRightAligned ? "flex" : "") +
                      "py-2 px-4 border-b border-background-800"
                    }
                  >
                    <div>{row[column.key]}</div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

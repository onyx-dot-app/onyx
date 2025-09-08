import { Persona } from "@/app/admin/assistants/interfaces";
import {
  FileOptionIcon,
  PDFIcon,
  TXTIcon,
  DOCIcon,
  HTMLIcon,
  JSONIcon,
  ImagesIcon,
  XMLIcon,
} from "@/components/icons/icons";
import { SearchResultIcon } from "@/components/SearchResultIcon";

export interface GridShape {
  encodedGrid: number;
  filledSquares: number;
}

export function generateRandomIconShape(): GridShape {
  const grid: boolean[][] = Array(4)
    .fill(null)
    .map(() => Array(4).fill(false));

  const centerSquares: number[][] = [
    [1, 1],
    [1, 2],
    [2, 1],
    [2, 2],
  ];

  shuffleArray(centerSquares);
  const centerFillCount = Math.floor(Math.random() * 2) + 3; // 3 or 4
  for (let i = 0; i < centerFillCount; i++) {
    const centerSquare: number[] | undefined = centerSquares[i];
    if (centerSquare === undefined) {
      continue;
    }

    const [row, col] = centerSquare;
    if (row === undefined || col === undefined) {
      continue;
    }

    const grid_row = grid[row];
    if (grid_row === undefined) {
      continue;
    }

    grid_row[col] = true;
  }
  // Randomly fill remaining squares up to 10 total
  const remainingSquares = [];
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const grid_row = grid[row];
      if (grid_row === undefined) {
        continue;
      }

      if (!grid_row[col]) {
        remainingSquares.push([row, col]);
      }
    }
  }
  shuffleArray(remainingSquares);

  let filledSquares = centerFillCount;
  for (const [row, col] of remainingSquares) {
    if (row === undefined || col == undefined) {
      continue;
    }

    if (filledSquares >= 10) break;

    const grid_row = grid[row];
    if (grid_row === undefined) {
      continue;
    }
    grid_row[col] = true;
    filledSquares++;
  }

  let path = "";
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const grid_row = grid[row];
      if (grid_row === undefined) {
        continue;
      }

      if (grid_row[col]) {
        const x = col * 12;
        const y = row * 12;
        path += `M ${x} ${y} L ${x + 12} ${y} L ${x + 12} ${y + 12} L ${x} ${
          y + 12
        } Z `;
      }
    }
  }
  const encodedGrid = encodeGrid(grid);
  return { encodedGrid, filledSquares };
}

function encodeGrid(grid: boolean[][]): number {
  let encoded = 0;
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const grid_row = grid[row];
      if (grid_row === undefined) {
        continue;
      }

      if (grid_row[col]) {
        encoded |= 1 << (row * 4 + col);
      }
    }
  }
  return encoded;
}

function decodeGrid(encoded: number): boolean[][] {
  const grid: boolean[][] = Array(4)
    .fill(null)
    .map(() => Array(4).fill(false));
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const grid_row = grid[row];
      if (grid_row === undefined) {
        continue;
      }

      if (encoded & (1 << (row * 4 + col))) {
        grid_row[col] = true;
      }
    }
  }
  return grid;
}

export function createSVG(
  shape: GridShape,
  color: string = "#FF6FBF",
  size: number = 48,
  padding?: boolean
) {
  const cellSize = size / 4;
  const grid = decodeGrid(shape.encodedGrid);

  let path = "";
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const grid_row = grid[row];
      if (grid_row === undefined) {
        continue;
      }

      if (grid_row[col]) {
        const x = col * 12;
        const y = row * 12;
        path += `M ${x} ${y} L ${x + 12} ${y} L ${x + 12} ${y + 12} L ${x} ${
          y + 12
        } Z `;
      }
    }
  }

  return (
    <svg
      className={`${padding && "p-1.5"}  m-auto`}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      xmlns="http://www.w3.org/2000/svg"
    >
      {grid.map((row, i) =>
        row.map(
          (cell, j) =>
            cell && (
              <rect
                key={`${i}-${j}`}
                x={j * cellSize}
                y={i * cellSize}
                width={cellSize}
                height={cellSize}
                fill={color}
              />
            )
        )
      )}
    </svg>
  );
}

function shuffleArray(array: any[]) {
  for (let i = array.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [array[i], array[j]] = [array[j], array[i]];
  }
}

// This is used for rendering a persona in the shared chat display
export const constructMiniFiedPersona = (
  assistant_icon_color: string | null,
  assistant_icon_shape: number | null,
  name: string,
  id: number
): Persona => {
  return {
    id,
    name,
    icon_color: assistant_icon_color ?? undefined,
    icon_shape: assistant_icon_shape ?? undefined,
    is_visible: true,
    is_public: true,
    display_priority: 0,
    description: "",
    document_sets: [],
    tools: [],
    owner: null,
    starter_messages: null,
    builtin_persona: false,
    is_default_persona: false,
    users: [],
    groups: [],
    user_file_ids: [],
    system_prompt: null,
    task_prompt: null,
    datetime_aware: true,
  };
};

export const getFileIconFromFileNameAndLink = (
  fileName: string,
  linkUrl?: string | null
) => {
  if (linkUrl) {
    return <SearchResultIcon url={linkUrl} />;
  }
  const extension = fileName.split(".").pop()?.toLowerCase();
  if (extension === "pdf") {
    return <PDFIcon className="h-4 w-4 shrink-0" />;
  } else if (extension === "txt") {
    return <TXTIcon className="h-4 w-4 shrink-0" />;
  } else if (extension === "doc" || extension === "docx") {
    return <DOCIcon className="h-4 w-4 shrink-0" />;
  } else if (extension === "html" || extension === "htm") {
    return <HTMLIcon className="h-4 w-4 shrink-0" />;
  } else if (extension === "json") {
    return <JSONIcon className="h-4 w-4 shrink-0" />;
  } else if (
    ["jpg", "jpeg", "png", "gif", "svg", "webp"].includes(extension || "")
  ) {
    return <ImagesIcon className="h-4 w-4 shrink-0" />;
  } else if (extension === "xml") {
    return <XMLIcon className="h-4 w-4 shrink-0" />;
  } else {
    if (fileName.includes(".")) {
      try {
        // Check if fileName could be a valid domain when prefixed with https://
        const url = new URL(`https://${fileName}`);
        if (url.hostname === fileName) {
          return <SearchResultIcon url={`https://${fileName}`} />;
        }
      } catch (e) {
        // If URL construction fails, it's not a valid domain
      }
      return <FileOptionIcon className="h-4 w-4 shrink-0" />;
    } else {
      return <FileOptionIcon className="h-4 w-4 shrink-0" />;
    }
  }
};

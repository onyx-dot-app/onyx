import { JSX } from "react";
import { UniqueIdentifier } from "@dnd-kit/core";

export interface Row {
  id: UniqueIdentifier;
  cells: (JSX.Element | string)[];
  staticModifiers?: [number, string][];
}

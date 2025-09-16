import { UniqueIdentifier } from "@dnd-kit/core";
import { JSX } from "react";

export interface Row {
  id: UniqueIdentifier;
  cells: (JSX.Element | string)[];
  staticModifiers?: [number, string][];
}

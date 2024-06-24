import { ToolSnapshot } from "./interfaces";
import { fetchSS } from "../utilsSS";

export async function fetchToolsSS(): Promise<ToolSnapshot[] | null> {
  try {
    const response = await fetchSS("/tool");
    if (!response.ok) {
      throw new Error(`Failed to fetch tools: ${await response.text()}`);
    }
    const tools: ToolSnapshot[] = await response.json();
    return tools;
  } catch (error) {
    console.error("Error fetching tools:", error);
    return null;
  }
}

export async function fetchToolByIdSS(
  toolId: string
): Promise<ToolSnapshot | null> {
  try {
    const response = await fetchSS(`/tool/${toolId}`);
    if (!response.ok) {
      throw new Error(
        `Failed to fetch tool with ID ${toolId}: ${await response.text()}`
      );
    }
    const tool: ToolSnapshot = await response.json();
    return tool;
  } catch (error) {
    console.error(`Error fetching tool with ID ${toolId}:`, error);
    return null;
  }
}

import { ToolSnapshot } from "./interfaces";

export async function fetchToolById(
  toolId: string
): Promise<ToolSnapshot | null> {
  try {
    const response = await fetch(`/api/tool/${toolId}`);
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

export async function fetchTools(): Promise<ToolSnapshot[] | null> {
  try {
    const response = await fetch("/api/tool");
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


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

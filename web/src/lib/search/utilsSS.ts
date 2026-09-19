import { DocumentSetSummary } from "../types";
import { fetchSS } from "../utilsSS";
import { Connector } from "../connectors/connectors";

export async function fetchValidFilterInfo() {
  const [connectorsResponse, documentSetResponse] = await Promise.all([
    fetchSS("/manage/connector"),
    fetchSS("/manage/document-set"),
  ]);

  let connectors: Connector<any>[] = [];
  if (connectorsResponse.ok) {
    connectors = await connectorsResponse.json();
  } else {
    console.log(
      `Failed to fetch connectors - ${connectorsResponse.status} - ${connectorsResponse.statusText}`
    );
  }

  let documentSets: DocumentSetSummary[] = [];
  if (documentSetResponse.ok) {
    documentSets = await documentSetResponse.json();
  } else {
    console.log(
      `Failed to fetch document sets - ${documentSetResponse.status} - ${documentSetResponse.statusText}`
    );
  }

  return { connectors, documentSets };
}

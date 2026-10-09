import {
  findTermRanges,
  getSearchTerms,
  matchesSourceOnly,
  searchDocumentSets,
} from "@/lib/documentSets/search";
import { ValidSources } from "@/lib/connectors/types/source";
import type {
  CCPairSummary,
  DocumentSetSummary,
  FederatedConnectorSummary,
} from "@/lib/types";

let nextId = 1;

function ccPair(name: string, source: ValidSources): CCPairSummary {
  return { id: nextId++, name, source, access_type: "public" };
}

function federatedSlack(channels: string[]): FederatedConnectorSummary {
  return {
    id: nextId++,
    name: "Federated Slack",
    source: "federated_slack",
    entities: { channels, include_dm: false },
  };
}

function documentSet(
  name: string,
  overrides: Partial<DocumentSetSummary> = {}
): DocumentSetSummary {
  return {
    id: nextId++,
    name,
    description: "",
    cc_pair_summaries: [],
    is_up_to_date: true,
    is_public: true,
    users: [],
    groups: [],
    permissions: {},
    federated_connector_summaries: [],
    ...overrides,
  };
}

const engineering = documentSet("Engineering Knowledge Base", {
  description: "Architecture docs and runbooks.",
  cc_pair_summaries: [ccPair("Engineering Wiki", ValidSources.Confluence)],
});
const escalations = documentSet("Customer Escalations", {
  description: "Escalated tickets and their engineering follow-ups.",
  cc_pair_summaries: [ccPair("Zendesk Tickets", ValidSources.Zendesk)],
});
const sales = documentSet("Sales Playbooks", {
  description: "Battlecards and pitch decks.",
  cc_pair_summaries: [ccPair("Sales Drive", ValidSources.GoogleDrive)],
});
const incidents = documentSet("Incident Response", {
  federated_connector_summaries: [federatedSlack(["incidents", "eng-oncall"])],
});
const allSets = [escalations, engineering, incidents, sales];

function names(documentSets: DocumentSetSummary[]): string[] {
  return documentSets.map((ds) => ds.name);
}

describe("getSearchTerms", () => {
  it("lowercases and splits on whitespace", () => {
    expect(getSearchTerms("  Eng   CONFLUENCE ")).toEqual([
      "eng",
      "confluence",
    ]);
    expect(getSearchTerms("   ")).toEqual([]);
  });
});

describe("searchDocumentSets", () => {
  it("returns the input unchanged for an empty query", () => {
    expect(searchDocumentSets(allSets, "  ")).toBe(allSets);
  });

  it("matches the name, ignoring case", () => {
    expect(names(searchDocumentSets(allSets, "PLAYBOOK"))).toEqual([
      "Sales Playbooks",
    ]);
  });

  it("matches the description", () => {
    expect(names(searchDocumentSets(allSets, "runbooks"))).toEqual([
      "Engineering Knowledge Base",
    ]);
  });

  it("matches a connector by its name or by its source", () => {
    expect(names(searchDocumentSets(allSets, "zendesk tickets"))).toEqual([
      "Customer Escalations",
    ]);
    expect(names(searchDocumentSets(allSets, "google drive"))).toEqual([
      "Sales Playbooks",
    ]);
    expect(names(searchDocumentSets(allSets, "confluence"))).toEqual([
      "Engineering Knowledge Base",
    ]);
  });

  it("matches a federated connector by its name or its entities", () => {
    expect(names(searchDocumentSets(allSets, "slack"))).toEqual([
      "Incident Response",
    ]);
    expect(names(searchDocumentSets(allSets, "oncall"))).toEqual([
      "Incident Response",
    ]);
  });

  it("requires every term to match, in any field", () => {
    expect(names(searchDocumentSets(allSets, "confluence knowledge"))).toEqual([
      "Engineering Knowledge Base",
    ]);
    expect(searchDocumentSets(allSets, "confluence zendesk")).toEqual([]);
  });

  it("puts name matches first and otherwise keeps the input order", () => {
    // "eng" is in one name, one description and one Slack channel.
    expect(names(searchDocumentSets(allSets, "eng"))).toEqual([
      "Engineering Knowledge Base",
      "Customer Escalations",
      "Incident Response",
    ]);
  });
});

describe("matchesSourceOnly", () => {
  const wiki = ccPair("Engineering Wiki", ValidSources.Confluence);

  it("is true when a term is only in the connector's source", () => {
    expect(matchesSourceOnly(wiki, ["confluence"])).toBe(true);
  });

  it("is false when the name already shows the term", () => {
    expect(matchesSourceOnly(wiki, ["wiki"])).toBe(false);
    expect(
      matchesSourceOnly(ccPair("Jira Cloud", ValidSources.Jira), ["jira"])
    ).toBe(false);
  });
});

describe("findTermRanges", () => {
  it("finds every occurrence of every term, ignoring case", () => {
    expect(findTermRanges("Eng and eng", ["eng"])).toEqual([
      [0, 3],
      [8, 11],
    ]);
  });

  it("merges overlapping and adjacent ranges", () => {
    expect(findTermRanges("Engineering", ["eng", "engine", "ering"])).toEqual([
      [0, 11],
    ]);
  });

  it("returns no ranges when nothing matches", () => {
    expect(findTermRanges("Sales", ["eng"])).toEqual([]);
    expect(findTermRanges("Sales", [])).toEqual([]);
  });
});

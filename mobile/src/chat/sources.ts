import type { IconFunctionComponent } from "@/icons/types";
import SvgFileText from "@/icons/file-text";
import SvgFolder from "@/icons/folder";
import SvgGlobe from "@/icons/globe";
import SvgMail from "@/icons/mail";
import SvgUploadCloud from "@/icons/upload-cloud";
import SvgAirtable from "@/logos/airtable";
import SvgAsana from "@/logos/asana";
import SvgAws from "@/logos/aws";
import SvgAxero from "@/logos/axero";
import SvgBitbucket from "@/logos/bitbucket";
import SvgBookstack from "@/logos/bookstack";
import SvgBraintrust from "@/logos/braintrust";
import SvgCanvas from "@/logos/canvas";
import SvgClickup from "@/logos/clickup";
import SvgCloudflare from "@/logos/cloudflare";
import SvgCoda from "@/logos/coda";
import SvgConfluence from "@/logos/confluence";
import SvgDiscord from "@/logos/discord";
import SvgDiscourse from "@/logos/discourse";
import SvgDocument360 from "@/logos/document-360";
import SvgDropbox from "@/logos/dropbox";
import SvgDrupal from "@/logos/drupal";
import SvgEgnyte from "@/logos/egnyte";
import SvgFireflies from "@/logos/fireflies";
import SvgFreshdesk from "@/logos/freshdesk";
import SvgGitbook from "@/logos/gitbook";
import SvgGithub from "@/logos/github";
import SvgGitlab from "@/logos/gitlab";
import SvgGmail from "@/logos/gmail";
import SvgGong from "@/logos/gong";
import SvgGoogleCloud from "@/logos/google-cloud";
import SvgGoogleDrive from "@/logos/google-drive";
import SvgGoogleSites from "@/logos/google-sites";
import SvgGuru from "@/logos/guru";
import SvgHighspot from "@/logos/highspot";
import SvgHubspot from "@/logos/hubspot";
import SvgJira from "@/logos/jira";
import SvgLinear from "@/logos/linear";
import SvgLoopio from "@/logos/loopio";
import SvgLumapps from "@/logos/lumapps";
import SvgMediawiki from "@/logos/mediawiki";
import SvgNotion from "@/logos/notion";
import SvgOracle from "@/logos/oracle";
import SvgOutline from "@/logos/outline";
import SvgProductboard from "@/logos/productboard";
import SvgSalesforce from "@/logos/salesforce";
import SvgSharepoint from "@/logos/sharepoint";
import SvgSlab from "@/logos/slab";
import SvgSlack from "@/logos/slack";
import SvgTeams from "@/logos/teams";
import SvgTestrail from "@/logos/testrail";
import SvgWikipedia from "@/logos/wikipedia";
import SvgXenforo from "@/logos/xenforo";
import SvgZendesk from "@/logos/zendesk";
import SvgZulip from "@/logos/zulip";

// The snake_case wire value, e.g. "web", "google_drive", "confluence".
export type DocumentSource = string;

// Subset of the backend's BaseFilters; the fields we omit default to null there.
export interface InternalSearchFilters {
  source_type: DocumentSource[] | null;
}

export interface SourceMeta {
  icon: IconFunctionComponent;
  displayName: string;
}

// A source missing here drops out of the picker, so `not_applicable` is deliberately absent.
const SOURCE_META: Record<DocumentSource, SourceMeta> = {
  confluence: { icon: SvgConfluence, displayName: "Confluence" },
  lumapps: { icon: SvgLumapps, displayName: "LumApps" },
  sharepoint: { icon: SvgSharepoint, displayName: "Sharepoint" },
  coda: { icon: SvgCoda, displayName: "Coda" },
  notion: { icon: SvgNotion, displayName: "Notion" },
  bookstack: { icon: SvgBookstack, displayName: "BookStack" },
  document360: { icon: SvgDocument360, displayName: "Document360" },
  discourse: { icon: SvgDiscourse, displayName: "Discourse" },
  gitbook: { icon: SvgGitbook, displayName: "GitBook" },
  slab: { icon: SvgSlab, displayName: "Slab" },
  outline: { icon: SvgOutline, displayName: "Outline" },
  google_sites: { icon: SvgGoogleSites, displayName: "Google Sites" },
  guru: { icon: SvgGuru, displayName: "Guru" },
  mediawiki: { icon: SvgMediawiki, displayName: "MediaWiki" },
  axero: { icon: SvgAxero, displayName: "Axero" },
  wikipedia: { icon: SvgWikipedia, displayName: "Wikipedia" },
  canvas: { icon: SvgCanvas, displayName: "Canvas" },
  drupal_wiki: { icon: SvgDrupal, displayName: "Drupal Wiki" },
  google_drive: { icon: SvgGoogleDrive, displayName: "Google Drive" },
  box: { icon: SvgFolder, displayName: "Box" },
  dropbox: { icon: SvgDropbox, displayName: "Dropbox" },
  s3: { icon: SvgAws, displayName: "S3" },
  google_cloud_storage: { icon: SvgGoogleCloud, displayName: "Google Storage" },
  egnyte: { icon: SvgEgnyte, displayName: "Egnyte" },
  oci_storage: { icon: SvgOracle, displayName: "Oracle Storage" },
  r2: { icon: SvgCloudflare, displayName: "R2" },
  jira: { icon: SvgJira, displayName: "Jira" },
  zendesk: { icon: SvgZendesk, displayName: "Zendesk" },
  airtable: { icon: SvgAirtable, displayName: "Airtable" },
  linear: { icon: SvgLinear, displayName: "Linear" },
  freshdesk: { icon: SvgFreshdesk, displayName: "Freshdesk" },
  asana: { icon: SvgAsana, displayName: "Asana" },
  clickup: { icon: SvgClickup, displayName: "Clickup" },
  productboard: { icon: SvgProductboard, displayName: "Productboard" },
  testrail: { icon: SvgTestrail, displayName: "TestRail" },
  slack: { icon: SvgSlack, displayName: "Slack" },
  teams: { icon: SvgTeams, displayName: "Teams" },
  gmail: { icon: SvgGmail, displayName: "Gmail" },
  imap: { icon: SvgMail, displayName: "Email" },
  discord: { icon: SvgDiscord, displayName: "Discord" },
  xenforo: { icon: SvgXenforo, displayName: "Xenforo" },
  zulip: { icon: SvgZulip, displayName: "Zulip" },
  salesforce: { icon: SvgSalesforce, displayName: "Salesforce" },
  hubspot: { icon: SvgHubspot, displayName: "HubSpot" },
  gong: { icon: SvgGong, displayName: "Gong" },
  fireflies: { icon: SvgFireflies, displayName: "Fireflies" },
  highspot: { icon: SvgHighspot, displayName: "Highspot" },
  loopio: { icon: SvgLoopio, displayName: "Loopio" },
  github: { icon: SvgGithub, displayName: "Github" },
  gitlab: { icon: SvgGitlab, displayName: "Gitlab" },
  bitbucket: { icon: SvgBitbucket, displayName: "Bitbucket" },
  web: { icon: SvgGlobe, displayName: "Web" },
  file: { icon: SvgFileText, displayName: "File" },
  user_file: { icon: SvgUploadCloud, displayName: "Uploaded Files" },
  craft_file: { icon: SvgFileText, displayName: "Your Files" },
  braintrust: { icon: SvgBraintrust, displayName: "Braintrust" },
  ingestion_api: { icon: SvgGlobe, displayName: "Ingestion" },
  mock_connector: { icon: SvgGlobe, displayName: "Mock Connector" },
};

// Exported so a test can prove every logo still renders.
export const KNOWN_SOURCES: DocumentSource[] = Object.keys(SOURCE_META);

// A federated connector shows as its indexed twin, so the prefix is stripped everywhere.
const FEDERATED_PREFIX = "federated_";

export function baseSourceType(source: DocumentSource): DocumentSource {
  return source.startsWith(FEDERATED_PREFIX)
    ? source.slice(FEDERATED_PREFIX.length)
    : source;
}

export function getSourceMeta(source: DocumentSource): SourceMeta | null {
  return SOURCE_META[baseSourceType(source)] ?? null;
}

export function configuredSources(
  availableSources: DocumentSource[],
): DocumentSource[] {
  const seen = new Set<DocumentSource>();
  const result: DocumentSource[] = [];
  for (const source of availableSources) {
    const base = baseSourceType(source);
    if (seen.has(base)) continue;
    seen.add(base);
    if (SOURCE_META[base]) result.push(base);
  }
  return result;
}

// A flag per source, so one switched off stays off while one that appears later defaults on.
export interface SourcePreferencesSnapshot {
  sourcePreferences: Record<DocumentSource, boolean>;
}

export function parseSourcePreferences(
  raw: string | null | undefined,
): SourcePreferencesSnapshot | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const preferences = (parsed as SourcePreferencesSnapshot)
      .sourcePreferences as unknown;
    if (
      typeof preferences !== "object" ||
      preferences === null ||
      Array.isArray(preferences)
    ) {
      return null;
    }
    if (
      Object.values(preferences).some((value) => typeof value !== "boolean")
    ) {
      return null;
    }
    return {
      sourcePreferences: preferences as Record<DocumentSource, boolean>,
    };
  } catch {
    return null;
  }
}

export function mergeSourcePreferences(
  configured: DocumentSource[],
  snapshot: SourcePreferencesSnapshot | null,
): DocumentSource[] {
  if (snapshot === null) return configured;
  const { sourcePreferences } = snapshot;
  return configured.filter((source) =>
    Object.prototype.hasOwnProperty.call(sourcePreferences, source)
      ? sourcePreferences[source]
      : true,
  );
}

/*
 * Folded into the previous snapshot, not rewritten from `configured` as web does — that forgets
 * choices made under a differently-scoped agent, and the key set is bounded by the catalogue.
 */
export function applySourcePreferences(
  enabled: DocumentSource[],
  configured: DocumentSource[],
  previous: SourcePreferencesSnapshot | null,
): SourcePreferencesSnapshot {
  const enabledSet = new Set(enabled);
  const sourcePreferences: Record<DocumentSource, boolean> = {
    ...(previous?.sourcePreferences ?? {}),
  };
  for (const source of configured) {
    sourcePreferences[source] = enabledSet.has(source);
  }
  return { sourcePreferences };
}

// null when nothing is selected → the backend applies no source filter.
export function buildInternalSearchFilters(
  selectedSources: DocumentSource[],
): InternalSearchFilters | null {
  if (selectedSources.length === 0) return null;
  return { source_type: selectedSources };
}

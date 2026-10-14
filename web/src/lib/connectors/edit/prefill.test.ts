import {
  buildEditProposal,
  editInitialValues,
  type ConnectorFormValues,
} from "@/lib/connectors/edit/prefill";
import { connectorConfigs } from "@/lib/connectors/connectors";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import type { AccessType } from "@/lib/types";

const CREDENTIAL_ID = 7;

function githubPair(
  config: Record<string, unknown>,
  overrides: Partial<CCPairFullInfo> = {}
): CCPairFullInfo {
  return {
    id: 3,
    name: "Docs repos",
    status: ConnectorCredentialPairStatus.ACTIVE,
    in_repeated_error_state: false,
    num_docs_indexed: 120,
    connector: {
      id: 11,
      name: "Docs repos",
      source: ValidSources.GitHub,
      input_type: "poll",
      connector_specific_config: config,
      refresh_freq: 1800,
      prune_freq: 86400,
      check_freq: null,
      // The API sends a naive UTC string.
      indexing_start: null,
      access_type: "public",
      credential_ids: [CREDENTIAL_ID],
      time_created: "2026-01-01T00:00:00Z",
      time_updated: "2026-01-01T00:00:00Z",
    },
    credential: {
      id: CREDENTIAL_ID,
      credential_json: {},
      admin_public: true,
      source: ValidSources.GitHub,
      user_id: null,
      user_email: null,
      user_personal_name: null,
      time_created: "2026-01-01T00:00:00Z",
      time_updated: "2026-01-01T00:00:00Z",
    },
    number_of_index_attempts: 1,
    last_index_attempt_status: "success",
    latest_deletion_attempt: null,
    access_type: "public",
    is_editable_for_current_user: true,
    permissions: { edit: true },
    deletion_failure_message: null,
    indexing: false,
    creator: null,
    creator_email: null,
    last_indexed: null,
    last_pruned: null,
    last_full_permission_sync: null,
    overall_indexing_speed: null,
    latest_checkpoint_description: null,
    last_permission_sync_attempt_status: null,
    permission_syncing: false,
    last_permission_sync_attempt_finished: null,
    last_permission_sync_attempt_error_message: null,
    supports_targeted_reindex: false,
    pending_backfills: [],
    has_named_checks: false,
    indexing_hold: null,
    ...overrides,
  };
}

const configuration = connectorConfigs[ValidSources.GitHub];

function proposalFor(
  ccPair: CCPairFullInfo,
  dataAccessGroupIds: number[] = [],
  edit: (values: ConnectorFormValues) => ConnectorFormValues = (values) =>
    values
) {
  const initialValues = editInitialValues(
    ValidSources.GitHub,
    configuration,
    ccPair,
    dataAccessGroupIds
  );
  return buildEditProposal({
    values: edit({ ...initialValues }),
    initialValues,
    configuration,
    ccPair,
    credentialId: CREDENTIAL_ID,
  });
}

describe("buildEditProposal", () => {
  it("proposes the pair's state when nothing changed", () => {
    const config = {
      repo_owner: "onyx-dot-app",
      repositories: "onyx,docs",
      include_prs: true,
      include_issues: false,
    };
    const ccPair = githubPair(config, {
      connector: {
        ...githubPair(config).connector,
        indexing_start: new Date("2025-03-04T05:06:07Z"),
      },
    });

    expect(proposalFor(ccPair)).toEqual({
      connector_specific_config: config,
      access_type: "public",
      data_access_group_ids: null,
      credential_id: CREDENTIAL_ID,
      indexing_start: "2025-03-04T05:06:07.000Z",
      name: "Docs repos",
      refresh_freq: 1800,
      prune_freq: 86400,
    });
  });

  it.each<[AccessType, number[]]>([
    ["private", [4, 2]],
    ["sync_restricted", [5]],
    ["sync", []],
  ])(
    "keeps the %s access and the pair's groups when nothing changed",
    (accessType, groupIds) => {
      const ccPair = githubPair(
        { repo_owner: "onyx-dot-app", repositories: "onyx" },
        { access_type: accessType }
      );

      const proposal = proposalFor(ccPair, groupIds);

      expect(proposal.access_type).toBe(accessType);
      // The editor may see only some groups: null keeps all of them.
      expect(proposal.data_access_group_ids).toBeNull();
    }
  );

  it("proposes the picked data-access groups when the access changed", () => {
    const ccPair = githubPair(
      { repo_owner: "onyx-dot-app", repositories: "onyx" },
      { access_type: "private" }
    );

    const proposal = proposalFor(ccPair, [4], (values) => ({
      ...values,
      data_access_group_ids: [7, 4],
    }));

    expect(proposal.access_type).toBe("private");
    expect(proposal.data_access_group_ids).toEqual([4, 7]);
  });

  it("proposes the changed values only", () => {
    const config = { repo_owner: "onyx-dot-app", repositories: "onyx" };
    const ccPair = githubPair(config);

    const proposal = proposalFor(ccPair, [], (values) => ({
      ...values,
      repositories: "onyx,docs",
      name: "Renamed",
      refreshFreq: 60,
    }));

    expect(proposal.connector_specific_config).toEqual({
      repo_owner: "onyx-dot-app",
      repositories: "onyx,docs",
    });
    expect(proposal.name).toBe("Renamed");
    expect(proposal.refresh_freq).toBe(3600);
    expect(proposal.prune_freq).toBe(86400);
  });

  it("picks the tab that takes no input when no tab field is stored", () => {
    const values = editInitialValues(
      ValidSources.GitHub,
      configuration,
      githubPair({ repo_owner: "onyx-dot-app" }),
      []
    );

    expect(values.github_mode).toBe("everything");
  });
});

describe("editInitialValues", () => {
  it("opens the Everything tab when only a supporting checkbox is stored", () => {
    const ccPair = githubPair({});
    const confluencePair: CCPairFullInfo = {
      ...ccPair,
      connector: {
        ...ccPair.connector,
        source: ValidSources.Confluence,
        connector_specific_config: {
          wiki_base: "https://acme.atlassian.net/wiki",
          is_cloud: true,
          space: "",
          page_id: "",
          cql_query: "",
          index_recursively: true,
        },
      },
    };

    const values = editInitialValues(
      ValidSources.Confluence,
      connectorConfigs[ValidSources.Confluence],
      confluencePair,
      []
    );

    expect(values.indexing_scope).toBe("everything");
  });

  it("fills the realm fields from the pair's credential", () => {
    const ccPair = githubPair({});
    const gitlabPair: CCPairFullInfo = {
      ...ccPair,
      connector: {
        ...ccPair.connector,
        source: ValidSources.GitLab,
        connector_specific_config: { project_owner: "acme" },
      },
      credential: {
        ...ccPair.credential,
        source: ValidSources.GitLab,
        credential_json: { gitlab_url: "https://gitlab.acme.com" },
      },
    };

    const values = editInitialValues(
      ValidSources.GitLab,
      connectorConfigs[ValidSources.GitLab],
      gitlabPair,
      []
    );

    expect(values.gitlab_url).toBe("https://gitlab.acme.com");
  });
});

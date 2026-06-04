import {
  availableBuiltInDescriptors,
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  ExternalAppType,
} from "@/app/craft/v1/apps/registry";

function descriptor(app_type: ExternalAppType): BuiltInExternalAppDescriptor {
  return {
    app_type,
    name: app_type,
    description: "",
    upstream_url_patterns: [],
    auth_template: {},
    required_org_credential_fields: [],
    setup_instructions: "",
    actions: [],
  };
}

function configuredApp(
  app_type: ExternalAppType,
  overrides: Partial<ExternalAppAdminResponse> = {}
): ExternalAppAdminResponse {
  return {
    id: 1,
    name: app_type,
    description: "",
    app_type,
    upstream_url_patterns: [],
    auth_template: {},
    organization_credentials: {},
    enabled: false,
    actions: [],
    is_onyx_managed: false,
    ...overrides,
  };
}

const ALL_DESCRIPTORS = [
  descriptor("SLACK"),
  descriptor("GOOGLE_CALENDAR"),
  descriptor("GMAIL"),
  descriptor("LINEAR"),
];

describe("availableBuiltInDescriptors", () => {
  it("returns every built-in when nothing is configured", () => {
    expect(availableBuiltInDescriptors(ALL_DESCRIPTORS, [])).toEqual(
      ALL_DESCRIPTORS
    );
  });

  it("hides a built-in once one of that type is configured (one-per-type)", () => {
    const available = availableBuiltInDescriptors(ALL_DESCRIPTORS, [
      configuredApp("LINEAR"),
    ]);
    expect(available.map((d) => d.app_type)).toEqual([
      "SLACK",
      "GOOGLE_CALENDAR",
      "GMAIL",
    ]);
  });

  it("hides multiple configured built-in types", () => {
    const available = availableBuiltInDescriptors(ALL_DESCRIPTORS, [
      configuredApp("LINEAR"),
      configuredApp("SLACK"),
    ]);
    expect(available.map((d) => d.app_type)).toEqual([
      "GOOGLE_CALENDAR",
      "GMAIL",
    ]);
  });

  it("hides Onyx-managed (cloud, pre-provisioned) built-ins, which are always configured", () => {
    const available = availableBuiltInDescriptors(ALL_DESCRIPTORS, [
      configuredApp("GMAIL", { is_onyx_managed: true }),
    ]);
    expect(available.map((d) => d.app_type)).not.toContain("GMAIL");
  });

  it("leaves built-ins available regardless of configured CUSTOM apps (custom may repeat)", () => {
    const available = availableBuiltInDescriptors(ALL_DESCRIPTORS, [
      configuredApp("CUSTOM", { id: 1 }),
      configuredApp("CUSTOM", { id: 2 }),
    ]);
    expect(available).toEqual(ALL_DESCRIPTORS);
  });
});

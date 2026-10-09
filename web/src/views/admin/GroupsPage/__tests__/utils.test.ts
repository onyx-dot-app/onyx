import { createTranslator } from "next-intl";
import en from "@/i18n/messages/en.json";
import ar from "@/i18n/messages/ar.json";
import type { UserGroup } from "@/lib/types";
import {
  buildGroupDescription,
  displayGroupName,
  formatMemberCount,
  type GroupsTranslate,
} from "@/views/admin/GroupsPage/utils";

const tEn = createTranslator({
  locale: "en",
  messages: en,
  namespace: "admin.groups",
}) as GroupsTranslate;
const tAr = createTranslator({
  locale: "ar",
  messages: ar,
  namespace: "admin.groups",
}) as GroupsTranslate;

function group(overrides: Partial<UserGroup>): UserGroup {
  return {
    id: 1,
    name: "Team",
    is_default: false,
    is_up_to_date: true,
    users: [],
    cc_pairs: [],
    document_sets: [],
    personas: [],
    ...overrides,
  } as UserGroup;
}

describe("displayGroupName", () => {
  it("translates the two built-in groups and leaves custom names alone", () => {
    expect(
      displayGroupName(group({ name: "Admin", is_default: true }), tAr)
    ).toBe("المشرفون");
    expect(
      displayGroupName(group({ name: "Basic", is_default: true }), tAr)
    ).toBe("أساسي");
    expect(displayGroupName(group({ name: "Admin" }), tAr)).toBe("Admin");
  });
});

describe("buildGroupDescription", () => {
  it("describes built-in groups from the catalog", () => {
    expect(
      buildGroupDescription(group({ name: "Basic", is_default: true }), tEn)
    ).toBe("Default group for all users with basic permissions.");
  });

  it("pluralizes resource counts and joins them", () => {
    const custom = group({
      cc_pairs: [{}, {}, {}] as UserGroup["cc_pairs"],
      document_sets: [{}] as UserGroup["document_sets"],
      personas: [{}, {}] as UserGroup["personas"],
    });
    expect(buildGroupDescription(custom, tEn)).toBe(
      "3 connectors · 1 document set · 2 agents"
    );
  });

  it("falls back to the empty label", () => {
    expect(buildGroupDescription(group({}), tEn)).toBe(
      "No private connectors / document sets / agents"
    );
  });
});

describe("formatMemberCount", () => {
  it("pluralizes in English and uses the Arabic forms", () => {
    expect(formatMemberCount(1, tEn)).toBe("1 Member");
    expect(formatMemberCount(306, tEn)).toBe("306 Members");
    expect(formatMemberCount(2, tAr)).toBe("عضوان");
  });
});

import type {
  BuiltinSkill,
  CustomSkill,
  SkillAuthor,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Mock authors
// ---------------------------------------------------------------------------

export const MOCK_CURRENT_USER: SkillAuthor = {
  id: "user-1",
  name: "Chris Weaver",
  email: "chris@onyx.app",
  is_admin: false,
};

/**
 * Synthetic "author" used to attribute built-in skills to Onyx itself.
 * Surfaces inside the author filter on the user-facing skills page.
 */
export const ONYX_BUILTIN_AUTHOR: SkillAuthor = {
  id: "onyx-builtin",
  name: "Onyx",
  email: "Onyx",
  is_admin: false,
};

const MOCK_ADMIN_AUTHOR: SkillAuthor = {
  id: "user-admin",
  name: "Onyx Admin",
  email: "admin@onyx.app",
  is_admin: true,
};

const MOCK_ALICE: SkillAuthor = {
  id: "user-2",
  name: "Alice Chen",
  email: "alice@onyx.app",
  is_admin: false,
};

const MOCK_BOB: SkillAuthor = {
  id: "user-3",
  name: "Bob Martinez",
  email: "bob@onyx.app",
  is_admin: false,
};

// ---------------------------------------------------------------------------
// Built-in skills
// ---------------------------------------------------------------------------

export const MOCK_BUILTIN_SKILLS: BuiltinSkill[] = [
  {
    slug: "pptx",
    name: "Presentations",
    description:
      "Read, edit, and create .pptx decks via LibreOffice + pptxgenjs.",
    available: true,
  },
  {
    slug: "image-generation",
    name: "Image generation",
    description: "Generate images via the Gemini Nano Banana image API.",
    available: false,
    unavailable_reason: "Requires GEMINI_API_KEY",
  },
  {
    slug: "company-search",
    name: "Company search",
    description:
      "Permissioned hybrid search over the user's accessible Onyx data.",
    available: true,
  },
];

// ---------------------------------------------------------------------------
// Custom skills (admin- and user-authored)
// ---------------------------------------------------------------------------

export const MOCK_CUSTOM_SKILLS: CustomSkill[] = [
  {
    id: "skill-1",
    slug: "deal-summary",
    name: "Deal summary",
    description:
      "Generate per-customer deal-status briefings from Salesforce + Onyx search.",
    author: MOCK_ADMIN_AUTHOR,
    visibility: "org_wide",
    shared_user_count: 0,
    shared_group_count: 0,
    enabled: true,
    promotion_requested: false,
    promoted_by_admin: false,
    bundle: {
      sha256:
        "5f7a92c1e8b4d3a6f0c9e2b8d4a7f1c3e5b9a2d8f6e4c1b3a9d5e8f2c7a4b6d1",
      total_bytes: 245_120,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 4_201,
          executable: false,
          kind: "markdown",
        },
        {
          path: "scripts/build_briefing.py",
          size_bytes: 12_482,
          executable: false,
          kind: "script",
        },
        {
          path: "templates/briefing.md",
          size_bytes: 1_842,
          executable: false,
          kind: "markdown",
        },
      ],
    },
    updated_at: "2026-04-12T14:33:00Z",
  },
  {
    id: "skill-2",
    slug: "rfp-helper",
    name: "RFP helper",
    description:
      "Pull boilerplate answers and security artifacts for RFP responses.",
    author: MOCK_ADMIN_AUTHOR,
    visibility: "groups",
    shared_user_count: 0,
    shared_group_count: 2,
    enabled: true,
    promotion_requested: false,
    promoted_by_admin: false,
    bundle: {
      sha256:
        "9b3e7f2a4c8d1e6b5a0f9c8e7d3b2a1f5e9c8d7a4b3f2e1d6a9c5b8e3f7a2d4c",
      total_bytes: 1_843_200,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 6_330,
          executable: false,
          kind: "markdown",
        },
        {
          path: "data/security_qna.json",
          size_bytes: 92_104,
          executable: false,
          kind: "data",
        },
        {
          path: "data/boilerplate.csv",
          size_bytes: 38_402,
          executable: false,
          kind: "data",
        },
        {
          path: "scripts/lookup.py",
          size_bytes: 8_204,
          executable: false,
          kind: "script",
        },
      ],
    },
    updated_at: "2026-04-29T09:12:00Z",
  },
  {
    id: "skill-3",
    slug: "nps-digest",
    name: "NPS digest",
    description:
      "Weekly NPS rollup with cohort breakdowns and outlier verbatims.",
    author: MOCK_ALICE,
    visibility: "users_and_groups",
    shared_user_count: 3,
    shared_group_count: 1,
    enabled: true,
    promotion_requested: true,
    promoted_by_admin: false,
    bundle: {
      sha256:
        "2a8f1e9c4b6d3a7f5e2c8b1d9a4f6e3c7b2d8a5f1e9c4b6d3a7f5e2c8b1d9a4f",
      total_bytes: 88_612,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 3_188,
          executable: false,
          kind: "markdown",
        },
        {
          path: "scripts/digest.py",
          size_bytes: 5_902,
          executable: false,
          kind: "script",
        },
      ],
    },
    updated_at: "2026-05-01T08:50:00Z",
  },
  {
    id: "skill-4",
    slug: "onboarding-buddy",
    name: "Onboarding buddy",
    description:
      "Build a tailored onboarding plan for a new hire from their role + team docs.",
    author: MOCK_CURRENT_USER,
    visibility: "private",
    shared_user_count: 0,
    shared_group_count: 0,
    enabled: true,
    promotion_requested: false,
    promoted_by_admin: false,
    bundle: {
      sha256:
        "1c4e7a9b2d5f8c1a4e7b9d2f5c8a1b4e7d9f2c5a8b1d4e7f9c2a5b8d1e4f7a9c",
      total_bytes: 12_440,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 2_801,
          executable: false,
          kind: "markdown",
        },
        {
          path: "templates/plan.md",
          size_bytes: 1_540,
          executable: false,
          kind: "markdown",
        },
      ],
    },
    updated_at: "2026-05-04T15:22:00Z",
  },
  {
    id: "skill-5",
    slug: "release-notes",
    name: "Release notes",
    description:
      "Draft customer-facing release notes from a list of merged PR titles.",
    author: MOCK_CURRENT_USER,
    visibility: "users_and_groups",
    shared_user_count: 1,
    shared_group_count: 1,
    enabled: true,
    promotion_requested: false,
    promoted_by_admin: false,
    bundle: {
      sha256:
        "8d2a5f1c9e4b7d3a6f0c2e5b8d1a4f7c9e2b5d8a1f4c7e0b3d6a9f2c5e8b1d4a",
      total_bytes: 18_204,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 3_402,
          executable: false,
          kind: "markdown",
        },
        {
          path: "scripts/format.py",
          size_bytes: 4_120,
          executable: false,
          kind: "script",
        },
      ],
    },
    updated_at: "2026-04-22T11:09:00Z",
  },
  {
    id: "skill-6",
    slug: "support-triage",
    name: "Support triage",
    description:
      "Classify inbound tickets and draft a first reply with sources.",
    author: MOCK_BOB,
    visibility: "org_wide",
    shared_user_count: 0,
    shared_group_count: 0,
    enabled: false,
    promotion_requested: false,
    promoted_by_admin: true,
    admin_disabled_reason: "Pending re-review after refund-flow change",
    bundle: {
      sha256:
        "4f8b2d6a1c5e9f3b7d0a4c8e2b6f1d5a9c3e7b1f5d9a2c6e0b4f8d2a6c1e5f9b",
      total_bytes: 56_402,
      files: [
        {
          path: "SKILL.md",
          size_bytes: 5_204,
          executable: false,
          kind: "markdown",
        },
        {
          path: "scripts/classify.sh",
          size_bytes: 1_820,
          executable: true,
          kind: "executable",
        },
        {
          path: "data/categories.json",
          size_bytes: 3_204,
          executable: false,
          kind: "data",
        },
      ],
    },
    updated_at: "2026-04-18T16:44:00Z",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function skillsOwnedBy(userId: string): CustomSkill[] {
  return MOCK_CUSTOM_SKILLS.filter((skill) => skill.author.id === userId);
}

export function skillsSharedWith(userId: string): CustomSkill[] {
  // For wireframe purposes, treat every "org_wide" + a couple of "groups" /
  // "users_and_groups" skills as shared with the current user, except those
  // they own themselves.
  return MOCK_CUSTOM_SKILLS.filter(
    (skill) =>
      skill.author.id !== userId &&
      skill.enabled &&
      (skill.visibility === "org_wide" ||
        skill.visibility === "groups" ||
        skill.visibility === "users_and_groups")
  );
}

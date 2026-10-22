import {
  getLtiTutorScopeError,
  includeLtiCourseRoot,
} from "@/refresh-pages/admin/TutorPage/utils";

describe("includeLtiCourseRoot", () => {
  it("defaults a new tutor to the current Canvas course root", () => {
    expect(includeLtiCourseRoot([], 42)).toEqual([42]);
  });

  it("preserves non-LTI tutor knowledge", () => {
    expect(includeLtiCourseRoot([7], null)).toEqual([7]);
  });

  it("does not duplicate an already-selected course root", () => {
    expect(includeLtiCourseRoot([42, 7], 42)).toEqual([42, 7]);
  });
});

describe("getLtiTutorScopeError", () => {
  it("blocks an LTI save until the Canvas course root is indexed", () => {
    expect(getLtiTutorScopeError("course-context", null)).toContain(
      "still indexing"
    );
  });

  it("allows non-LTI saves without a Canvas course root", () => {
    expect(getLtiTutorScopeError(null, null)).toBeNull();
  });
});

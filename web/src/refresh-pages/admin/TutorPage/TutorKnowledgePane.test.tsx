import { render, screen } from "@testing-library/react";
import TutorKnowledgePane from "@/refresh-pages/admin/TutorPage/TutorKnowledgePane";

jest.mock("@/sections/knowledge/SourceHierarchyBrowser", () => ({
  __esModule: true,
  default: () => null,
}));

const knowledgeUrl =
  "/tutor?lti_context_id=course-123&lti_canvas_course_node_id=456&projectId=789&embedded=true&tab=knowledge";

test("opens content management in the current LTI frame with the course context", () => {
  render(
    <TutorKnowledgePane
      selectedDocumentIds={[]}
      onDocumentIdsChange={jest.fn()}
      selectedFolderIds={[]}
      onFolderIdsChange={jest.fn()}
      canvasCourseNodeId={null}
      ltiContextId="course-123"
      knowledgeUrl={knowledgeUrl}
    />
  );

  const link = screen.getByRole("link", { name: "Add or manage content" });
  expect(link).toHaveAttribute("href", knowledgeUrl);
  expect(link).toHaveAttribute("target", "_self");
});

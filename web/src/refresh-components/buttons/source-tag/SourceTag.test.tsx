import { render, screen, setupUser } from "@tests/setup/test-utils";
import { ValidSources } from "@/lib/connectors/types/source";
import SourceTag from "./SourceTag";

const source = {
  id: "doc-1",
  title: "Rate limit headers inconsistent across endpoints",
  sourceType: ValidSources.Jira,
};

test("hovering an inline citation shows its details card", async () => {
  const user = setupUser();
  render(
    <SourceTag
      variant="inlineCitation"
      displayName="Jira"
      sources={[source]}
      showDetailsCard
    />
  );

  // A real pointer lands on the Badge's title, inside its own tooltips.
  await user.hover(screen.getByText("Jira"));

  // Radix also renders a hidden copy of the card for screen readers.
  expect((await screen.findAllByText(source.title)).length).toBeGreaterThan(0);
});

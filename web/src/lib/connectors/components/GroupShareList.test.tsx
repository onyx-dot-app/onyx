import { render, screen } from "@tests/setup/test-utils";
import { Formik } from "formik";
import GroupShareList from "@/lib/connectors/components/GroupShareList";
import { Tier } from "@/lib/tiers/types";

jest.mock("@/lib/tiers/hooks", () => ({
  ...jest.requireActual("@/lib/tiers/hooks"),
  useTierAtLeast: () => false,
}));
jest.mock("@/lib/hooks", () => ({
  useUserGroups: jest.fn(),
}));

const { useUserGroups } = jest.requireMock("@/lib/hooks");

describe("GroupShareList below its required tier", () => {
  it("does not request the groups, and shows no load error", () => {
    useUserGroups.mockReturnValue({
      data: [],
      isLoading: false,
      error: "",
    });
    render(
      <Formik initialValues={{ groups: [] }} onSubmit={() => {}}>
        <GroupShareList
          name="groups"
          label="Groups"
          placeholder="Add groups"
          requiredTier={Tier.BUSINESS}
        />
      </Formik>
    );

    expect(useUserGroups).toHaveBeenCalledWith(false);
    expect(
      screen.queryByText("Could not load groups. Reload the page to try again.")
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add groups")).toBeEnabled();
  });
});

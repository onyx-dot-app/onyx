import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Formik } from "formik";
import GroupShareList from "@/lib/connectors/components/GroupShareList";
import { Tier } from "@/lib/tiers/types";
import { SvgUserManage } from "@opal/icons";

jest.mock("@/lib/tiers/hooks", () => ({
  ...jest.requireActual("@/lib/tiers/hooks"),
  useTierAtLeast: () => false,
}));
jest.mock("@/lib/hooks", () => ({
  useUserGroups: jest.fn(),
}));

const { useUserGroups } = jest.requireMock("@/lib/hooks");

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

function renderLocked() {
  return render(
    <Formik initialValues={{ groups: [] }} onSubmit={() => {}}>
      <GroupShareList
        name="groups"
        label="Groups"
        placeholder="Add groups"
        requiredTier={Tier.BUSINESS}
        lockedRows={[
          {
            id: "admins",
            name: "Admins",
            icon: SvgUserManage,
            note: "Always shared",
          },
        ]}
      />
    </Formik>
  );
}

describe("GroupShareList below its required tier", () => {
  beforeEach(() => {
    useUserGroups.mockReturnValue({
      data: [],
      isLoading: false,
      error: "",
    });
  });

  it("does not request the groups, and shows no load error", () => {
    renderLocked();

    expect(useUserGroups).toHaveBeenCalledWith(false);
    expect(
      screen.queryByText("Could not load groups. Reload the page to try again.")
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add groups")).toBeEnabled();
  });

  it("lists the fixed rows, locked, under the plan heading", async () => {
    const user = userEvent.setup({ delay: null });
    renderLocked();

    await user.click(screen.getByPlaceholderText("Add groups"));

    expect(
      await screen.findByText("Available for Business Plan")
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Admins/ })).toHaveAttribute(
      "aria-disabled",
      "true"
    );
  });
});

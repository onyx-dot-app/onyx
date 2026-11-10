import { render, screen, setupUser } from "@tests/setup/test-utils";
import { TextButton } from "@opal/components";
import type { FormEvent } from "react";

test("text actions support keyboard activation without submitting a form", async () => {
  const user = setupUser();
  const onClick = jest.fn();
  const onSubmit = jest.fn((event: FormEvent) => event.preventDefault());
  render(
    <form onSubmit={onSubmit}>
      <TextButton nowrap={false} onClick={onClick}>
        Disconnect to reconnect
      </TextButton>
    </form>
  );
  await user.tab();
  expect(screen.getByRole("button")).toHaveFocus();
  await user.keyboard("{Enter}");
  await user.keyboard(" ");
  expect(onClick).toHaveBeenCalledTimes(2);
  expect(onSubmit).not.toHaveBeenCalled();
});

test("disabled text actions cannot activate or receive keyboard focus", async () => {
  const user = setupUser();
  const onClick = jest.fn();
  render(
    <TextButton disabled onClick={onClick}>
      Disconnect
    </TextButton>
  );
  const action = screen.getByRole("button", { name: "Disconnect" });
  expect(action).toBeDisabled();
  await user.click(action);
  await user.tab();
  expect(action).not.toHaveFocus();
  expect(onClick).not.toHaveBeenCalled();
});

import {
  isStillOnLocation,
  locationKey,
} from "@/app/app/services/submitLocation";

const startKeys = [
  locationKey("/app", new URLSearchParams("projectId=7")),
  locationKey("/app", new URLSearchParams()),
];

test("matches the start location before the send removes the project", () => {
  expect(
    isStillOnLocation(startKeys, { pathname: "/app", search: "?projectId=7" })
  ).toBe(true);
});

test("matches the start location after the send removes the project", () => {
  expect(isStillOnLocation(startKeys, { pathname: "/app", search: "" })).toBe(
    true
  );
});

test("does not match after the user opens a different chat", () => {
  expect(
    isStillOnLocation(startKeys, {
      pathname: "/app",
      search: "?chatId=other-chat",
    })
  ).toBe(false);
});

test("does not match after the user opens a different project", () => {
  expect(
    isStillOnLocation(startKeys, { pathname: "/app", search: "?projectId=8" })
  ).toBe(false);
});

test("does not match after the user opens a different page", () => {
  expect(
    isStillOnLocation(startKeys, { pathname: "/app/agents", search: "" })
  ).toBe(false);
});

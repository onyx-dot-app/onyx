import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

const store = () => useBuildSessionStore.getState();

beforeEach(() => {
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    noSessionOutputPanelOpen: false,
    noSessionActiveOutputTab: "files",
  });
});

it.each(["create", "select"] as const)(
  "preserves the open welcome panel and its tab when initializing via %s",
  (initialize) => {
    store().setCurrentSession(null);
    store().toggleCurrentOutputPanel();
    expect(store().noSessionActiveOutputTab).toBe("files");

    const newSessionId = "from-welcome";
    if (initialize === "create") store().createSession(newSessionId);
    store().setCurrentSession(newSessionId);

    expect(store().sessions.get(newSessionId)).toMatchObject({
      outputPanelOpen: true,
      activeOutputTab: "files",
      tabHistory: {
        entries: [{ type: "pinned", tab: "files" }],
        currentIndex: 0,
      },
    });
  }
);

it("keeps Preview as the default when opening a saved session directly", () => {
  store().setCurrentSession(null);
  store().setCurrentSession("saved-session");
  expect(store().sessions.get("saved-session")?.activeOutputTab).toBe(
    "preview"
  );
});

it("honors an explicit initial tab instead of the welcome selection", () => {
  store().setCurrentSession(null);
  store().createSession("explicit-preview", { activeOutputTab: "preview" });
  expect(store().sessions.get("explicit-preview")).toMatchObject({
    activeOutputTab: "preview",
    tabHistory: { entries: [{ type: "pinned", tab: "preview" }] },
  });
});

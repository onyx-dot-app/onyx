import { createSlackChannelConfig } from "../lib";

afterEach(() => {
  jest.restoreAllMocks();
});

test("includes the feedback-button preference in channel configuration requests", async () => {
  const fetchSpy = jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
  } as Response);
  const creationRequest = {
    slack_bot_id: 1,
    document_sets: [],
    persona_id: null,
    enable_auto_filters: false,
    channel_name: "general",
    answer_validity_check_enabled: false,
    questionmark_prefilter_enabled: false,
    respond_tag_only: false,
    is_ephemeral: false,
    respond_to_bots: false,
    show_continue_in_web_ui: true,
    remove_feedback_buttons: true,
    respond_member_group_list: [],
    usePersona: false,
    response_type: "citations" as const,
    standard_answer_categories: [],
    disabled: false,
  };

  await createSlackChannelConfig(creationRequest);

  const [, requestInit] = fetchSpy.mock.calls[0]!;
  const requestBody = JSON.parse(requestInit?.body as string);
  expect(requestBody.remove_feedback_buttons).toBe(true);
});

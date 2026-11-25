# Chat Frontend

> The web chat at `/app`: it sends a turn, reads the packet stream, keeps each
> session's message tree in a client store, and renders timeline steps and the
> answer. It also drives the actions that change the saved conversation, and
> owns the development proxy that forwards `/api` to the backend.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **A new user meets first-run onboarding** on the chat page. A user with no
  name gives one. An admin also connects an LLM provider, then sees optional
  setup cards and a final step. The chat input stays locked until the optional
  setup step. An admin who leaves part way resumes at the saved step, or at the
  optional setup step when the required steps are done. Finishing or hiding
  the steps, or sending a message, ends onboarding in that browser.
- **A user sends a message** and watches it work: reasoning, search and other
  tool steps appear as a timeline, then the answer streams with citation chips.
  The user can stop the answer until its stop packet arrives. The partial
  answer stays, marked as stopped. After the stop packet, Stop goes away while
  the answer finishes drawing. The input stays busy until the server confirms
  that the turn is saved. Text sent before then becomes pending input, which
  the server starts. If the
  client cannot confirm the turn, the send button changes to a manual check,
  and the typed text stays. A failed refresh of a server-started turn uses the
  same recovery action.
- **A user types while an answer streams.** Enter and the send arrow add text
  at the next model step by default. The account's Send Behavior setting can
  make them interrupt instead. Ctrl/Cmd+Enter always queues the next turn.
  Each pending message has Send now, which interrupts current work first.
  Arrow keys in the empty input highlight a pending message, and Enter sends
  it now. Interrupting also stops speech playback. Queued text survives reload
  and browser closure. A send that arrives
  after the response ends becomes a queued turn. One pending request runs at a
  time; text sent meanwhile stays in the input. Editing withdraws the pending
  message before its text returns to the input; accepted messages cannot be
  withdrawn. Stop and failed responses pause the queue; a step limit does not.
  A pending message carries the skills picked in it with `@`
  ([[skills]]): sent into the running response, they apply to that response.
  Pending submission takes no attached files and is unavailable in incognito
  and for anonymous users. Craft keeps its own queue; only the queue display and
  keyboard navigation are shared.
- **A user drives the chat from the keyboard.** Cmd/Ctrl+Shift+O starts a
  new session, Cmd/Ctrl+E folds the sidebar, Cmd/Ctrl+/ opens or closes the
  model picker, Alt+Up and Alt+Down open the previous or next Recents chat,
  and Cmd+Option on Mac or Ctrl+Alt with 1–9 opens the Nth Recents chat.
  Holding those modifiers shows the shortcut at the end of each chat row. All but
  Alt+Up and Alt+Down work from the chat input too, since those keys move
  the caret by paragraph on macOS. Only the sidebar shortcut runs while
  another modal is open.
  `web/src/lib/shortcuts/constants.ts` lists them;
  `sections/sidebar/ChatShortcuts.tsx` binds them with Opal's `useHotkey`.
  Cmd/Ctrl+K opens or closes the sidebar's search menu
  (`sections/sidebar/ChatSearchCommandMenu.tsx`). The menu shows Recent
  Sessions and Shortcuts. Search matches chat sessions and shortcut labels.
  Shortcuts includes New Session and shows the keys for the user's platform.
  Each shortcut action runs after the menu closes.
- **A user finds text in the open chat.** Cmd/Ctrl+F opens a find bar
  (`sections/chat/ChatFind.tsx`) in the `overlay` slot of the chat's
  `ChatScrollContainer`; with no chat open, the browser's find stays. It
  searches the loaded messages' data, not the DOM: user text and answer
  text, without tool steps or thinking (`lib/chatFind/match.ts`). It parses
  answers with `AnswerMarkdown`'s remark plugins
  (`lib/answerText/remarkPlugins.ts`), so the counts match the page. So it also
  finds rows that the windowed list has unmounted. A step scrolls the row
  near the view so it mounts, then the CSS Custom Highlight API paints the
  matches inside rows marked `data-chat-find-text`
  (`lib/chatFind/highlights.ts`, `lib/chatFind/hooks.ts`). Citation chips and
  callout titles are marked `data-chat-find-ignore`; footnotes are left out.
  It searches every answer of a multi-model turn and the user messages a
  reply shows in place. A match in a closed `<details>` opens it, and one
  below a long question's fold unfolds the bubble (`data-chat-find-fold`). A search starts at the top row of the view.
  Enter and Shift+Enter step; Escape closes and returns focus.
- **A user types or pastes with no field focused.** On the chat page, a
  printable key with no Ctrl, Cmd or Alt moves focus to the chat input, and
  the browser types the character there. A paste goes to the input too. Keys
  in a field, Space on a button, and keys while a dialog, menu or listbox is
  open stay where they are (`web/src/lib/chat/typeToFocus.ts`). The handlers
  are React props on the page's root element in `views/AppPage.tsx`, which
  takes focus (`tabIndex={-1}`) on a click in empty space. So only keys with
  focus inside the page count: not keys on the sidebar, or on `body` before
  the first click.
- **The composer keeps a draft for each chat** and one for the new chat
  (`sections/input/AppInputBar.tsx`, `useDraft` with `storage: "local"`). The
  draft holds the text, its `@` picks and the uploaded files, and survives
  reload and browser closure. A send or an emptied input clears it, and
  logout removes all of them. Incognito keeps its composer text and files
  in memory. Persisted drafts are scoped to the signed-in account and tenant.
  Drafts from older tabs without an account or privacy mode are not restored.
- **Subagents can continue after the answer ends.** A small activity indicator
  stays visible while background work remains. It shares a row with the
  pending-input hint. Its Stop subagents button stops every active
  background agent on the selected branch; it sits outside the `role="status"`
  text, so the live region announces only the status. The input stays usable. While
  subagents run, status polling finds automatic follow-up responses in an idle
  chat and loads them through the normal refresh and replay path. Internal
  agent results do not become user message bubbles. A "Subagent results received" divider shows above each
  automatic follow-up response. That response shows its model label but
  cannot be regenerated.
- **A tool call needs approval.** An approval card shows the payload that
  the tool gives for the call (`ToolApprovalRequest.arguments`), or the call's arguments
  when the tool gives none. Every card that waits for a decision shows in one region after
  the last message (`sections/chat/ToolApprovalsRegion.tsx`, rendered by
  `ChatUI`), oldest response first and in packet order, from the replies and
  from their background subagents alike. A multi-model card names its model;
  a subagent's card (`agent_name` set) names the subagent. The request has no
  deadline. The user approves once, approves for the chat, or rejects; the
  card then becomes a one-line record of the outcome, or of "No longer
  waiting" when the server returns 409 or 404. The record shows in the region
  until the resolution packet arrives; from then on the reply's timeline
  shows it next to its tool call (`AgentMessage:buildSectionSegments`), and
  a reload replays it there. While the turn waits, its stream ends with
  `stop(awaiting_user)` and the chat goes idle. That stop pauses the
  answer: `processPackets` does not count it. No stop changes a card: the
  server sends `tool_approval_resolved` for every request that it ends, live
  and in replay, with `cancelled` when there is no decision. A card's status
  comes only from that outcome, or from this client's decision until the
  outcome arrives (`lib/chat/toolApprovals.ts:toolApprovalStatus`). A
  continuation sends a resolution again live after its replay sent it; the
  read keeps one entry per `approval_id`. The decision response names the
  resume stream of a suspended answer in `continuation` (`ToolApprovalCard`);
  for an answer that still runs it is null and the current reader keeps
  reading. The client does not decide which decision was the last: "Approve
  for this chat" can also approve sibling requests on the server. When
  `continuation` is set, `lib/chat/settleChatSession.ts:followChatStream`
  follows that stream from cursor 0 into the rows that its `response_ids`
  name, unless this browser already reads it (the send reader and every
  replay reader claim their stream, `claimStreamReader`) or those rows are
  not loaded. A claim also takes over the stream's answers: an older reader
  of an answer skips it (`writesAnswer`), even after the newer reader ends,
  and both the send reader and a
  replay reader merge their answers into the current tree. Without a `continuation`, an incognito chat waits for the next
  stream (`waitForChatResponseEnd`) and follows it. When none comes because
  the continuation already ended, the card refreshes the chat. An incognito
  chat has no server queue, but `useChatSessionQueue` still reads its status,
  so a background agent's request also refreshes it. An incognito refresh
  keeps local content: only answers whose saved copies hold approval
  requests take those copies, since only a chat that saves content can ask
  for approval. A loaded older answer outside the latest page that still
  shows a waiting card was resolved elsewhere, so the refresh reads it again
  from the page that ends at it (`fetchSettledChatSession` with
  `beforeMessageId`). A stream that ends
  with `stop(awaiting_user)` settles like any other: the status reads
  follow a new `current_stream` until the session is idle. After a 409 or
  404 decision, the card reads the status once and follows `current_stream`
  while the server processes it. A subagent's requests and resolutions
  arrive in the root reply that started it, at its `spawn_agent` or
  `send_message` card, through a load or a continuation's replay, never in a
  live stream. Each load records its `approvals_version` in the session
  store; in an idle chat `useChatSessionQueue` calls `refreshChatSession`
  when the status's version differs from the loaded one. The version is
  empty while the chat has no request, and a chat that this browser started
  compares against that empty version: a clean send keeps its streamed
  messages, and any request refreshes the chat. A decided agent
  request sets `has_active_subagents` until the agent finishes or waits
  again, so a decision on a subagent's card reads the status once; the
  status then polls while background work runs, and each version change
  refreshes the chat with the agent's later cards. A suspended turn has no Stop: the user decides each card. Stop shows only while the turn is live; the server then rejects every
  open request of the reply, and the record reads "Not approved". A reload
  replays the request and the stop the same way.
  While a reply's own card waits, the timeline header reads "Waiting for your
  approval", also after a preamble and for parallel tool calls. The server
  refuses new input with a 409 `APPROVAL_PENDING`; the client does not check
  first. On that 409 the composer keeps the draft, scrolls to the reply's
  first waiting card in the region, approval or question, shakes it and
  shows a toast that names what waits
  (`lib/chat/hooks.ts:useShowPendingRequest`). When the chat shows no such
  card, for example for a turn that another tab started, the saved session
  supplies it: a refused send's settlement loads it, and an idle chat
  refreshes. A subagent's card blocks no send.
  What each decision does is in [[mcp-and-custom-tools]].
- **The agent asks the user questions.** A question card
  (`ToolQuestionCard`) shows 1-4 questions, one per page; each offers its
  options in the model's order, recommended first, and an "Other" field
  for the user's own answer. A card with more than one question shows "Question N of M"
  and Back and Next buttons; the choices stay when the page changes, and
  picking an option does not change the page. For a single-select question
  the user picks one option (a radio group) or writes in Other; typing in
  Other clears the option and picking an option clears Other. A question
  with `multi_select` reads "Choose all that apply." and shows its options
  as checkboxes; the user toggles any of them and can also write in Other.
  The record joins several chosen options as a list. The user submits on the last page,
  where Submit replaces Next. Submit stays disabled, with a hint that
  names the unanswered questions, until each question has an answer.
  Waiting cards show in their own region after the approval
  region (`sections/chat/ToolQuestionsRegion.tsx`); a question has no model
  label, since only a single-model reply's root agent asks. The packets,
  the answers route and the replay are in [[streaming-protocol]] and
  [[mcp-and-custom-tools]]. Questions share the approval reads and UI
  state in `lib/chat/toolApprovals.ts`: `readToolQuestions` reads them
  with the same cache as `readToolApprovals`, `readWaitingToolRequests`
  lists both kinds on the selected branch, and `useToolRequestUi` holds
  the local statuses of both and the nudge. The card's answered status
  shows until `tool_question_resolved` arrives; a 409 or 404 makes it "No
  longer waiting", and the card follows the continuation exactly as an
  approval card does (`lib/chat/hooks.ts:useFollowUserInput`). While a
  question waits, the timeline header reads "Waiting for your answer"
  (`useToolRequests` gives `awaiting`). The options of a page are one radio
  group: one tab stop, arrow keys, Home and End move the choice. One read,
  `readWaitingQuestions`, gives the waiting questions with this client's
  local status; the region, the composer and `useShowPendingRequest` use
  it, and only a question without a local status still waits for the
  user. While such a question waits on the selected branch, text sent from
  the composer answers every waiting question of that reply instead of
  starting a turn, also while a foreground part of the reply still runs
  (`useWaitingQuestionIds`, `useAnswerWithMessage`); the questions then
  show as answered until their resolution arrives. Stop stays next to the
  send button while the reply streams. An answer takes no files: with
  files attached, the composer holds the text and says why. The text
  leaves the composer and comes back if the server refuses it: a 409
  `APPROVAL_PENDING` nudges the reply's waiting approval card, another 409
  or a 404 marks the questions "No longer waiting", and any other refusal
  (a query-hook rejection, 413 for a long text) shows the server's reason
  in a toast. After the resolution,
  the reply's timeline shows the record: each card answer as
  "Header: option (note)", "Answered in the chat", or "Not answered" for a
  question that a stop cancelled. A typed answer
  (`tool_question_resolved.message`) shows as the user's message bubble
  after the record, and later output follows it (`AgentMessage` splits the
  section there); a reload replays the same.
- **A user edits or regenerates** an earlier message. A switcher then moves
  between the versions, and the rest of the chat follows the chosen one. A
  reload shows the same version. Edit loads the message's text and files into
  the composer (`AppInputBarHandle.editMessage`) under an "Editing in the
  composer" banner, and sets the draft aside. Cancel, Escape or the send
  puts the draft back. The send resends with `messageIdToResend` and the
  composer's files; a kept file keeps its original descriptor.
- **A user sends one message to several models** and sees the answers side by
  side. They can pick one. If they send a follow-up without a pick, the chat
  continues from the answer they were looking at.
- **A user attaches files** by drag and drop, paste or the input bar. While
  files are dragged over the chat page, an overlay says "Drop files to
  attach" (`sections/input/FileDropOverlay.tsx`). If the
  active model has no vision support, an upload that contains an image is
  refused with a message, and none of its files attach.
- **A user reloads during an answer.** The buffered part appears at once,
  without animation, and the rest streams live. With several models, each
  answer gets its own part. If the stream drops while the run continues, the
  chat attaches again and later output, such as an approval card, still
  appears.
- **The model publishes files from its sandbox.** While a turn runs, its
  reply shows no file cards; the right panel and its toggle update live. When
  the turn ends (stopped and failed turns too), each file that the turn
  published shows as a download card after the answer, with its title (else
  its file name), type and size. As in Craft, a reply shows at most five
  cards of the chat's own files, then a "View all N files" button that opens
  the panel's Files list; a file of another chat, which that list leaves out,
  always shows as a card (`belongsToChat`, the chat ID from
  `PublishedFilesPanel`). A page without the panel shows every card. Every publish of one path in a chat is a version of one
  artifact (`artifact_id`, `version`). A click opens the card's version in
  its artifact's tab in the right panel; a page without the panel (NRF)
  opens it in the preview modal. Each card shows only its file; a later publish of the same path adds
  a card of its own. Cards that show one name also show their
  `display_path`, which the backend sends: relative to the chat's working
  directory, or the whole path outside it. The path shows under the title, before the type and size, in an
  LTR code span, and the type shows only for an extension of ASCII letters
  and digits. The timeline step lists the
  files that the call asked for and how it ended. Shared chats show the same
  cards.
- **A chat has a right panel, with a toggle at the far end of its header**
  (the shared view's header for a shared chat), with or without published
  files. The toggle sits over the workspace's top end, so it stays at the
  same place over the header, the panel beside the page and a panel over it.
  The panel's controls keep out of its room
  (`--panel-toggle-reserve` in `app/globals.css`). The header keeps out of
  it only while the panel is closed; beside the open panel, which holds the
  toggle, the share button keeps only the header's padding. It has one label and
  `aria-expanded`, and it acts on what the user sees: on a shown panel it
  closes any tab, Sources too; on a hidden panel, also one whose stored state
  shows Sources that the page hides, it shows the last shown Files tab, else
  the Files list, whose empty state says that the chat has no files. The panel
  has no close button of its own. The right panel looks and
  behaves like Craft's output panel: a tab strip (Files, Sources, and a
  closable tab per opened file), a URL bar, and the active tab's content. As
  in Craft's, the URL bar of a Files tab starts with a refresh button, which
  loads the chat's file list again
  (`lib/chat/pagedSession.ts:reloadChatPublishedFiles`, the latest page of
  `get-chat-session`, which has the server's list; a shared chat reads its
  `is_shared` page). An open file's tab keeps showing its file; the list shows
  the newer publishes. Every load of a chat page takes a sequence as its fetch
  starts (`lib/chat/publishedFiles.ts:startChatLoad`), and a load's list
  replaces the chat's list only when no load that started later gave it, so an
  older load never overwrites a newer list. The button is off while the reload
  runs, and a failure shows a toast. Settlement runs the same reload when a
  settled stream's answers hold a finished `library_manage_library` or
  `artifact` call (a `custom_tool_delta`), whose changes send no file packets,
  unless it loaded the saved history. A file tab's URL bar shows the file's
  path, then the preview's actions: source toggle, copy and download. It
  opens at half the page; the user drags its edge, or uses the arrow keys on
  the edge, to resize it, and the width is kept per chat through a reload. A
  button expands it over the whole page and back. A page too narrow for both
  the chat and the panel shows the panel over the page, without the size
  button. A panel over the page covers only the page column,
  not the sidebar, and the page under it cannot be focused. Files and Sources
  lead the tab strip when they have content, or while they are active. A citation's Sources control opens the panel on Sources. The
  Files tab shows Craft's output tiles for the files published in the chat,
  on every branch, also by answers that are not loaded and by subagents: one
  tile per artifact, its newest version, newest artifact first (a new
  version keeps its artifact's place), with its title or else its
  name, and a search in the URL bar. A text, markdown or CSV tile up to 256 KB
  shows the start of its file, scaled down, and an SVG tile draws its image
  from the same text, once it nears the view
  (`SWR_KEYS.chatFileTileText`), read through the preview's bounded
  `loadChatFilePreview`; it loads at most once per file and session,
  and a failure is kept as well, so a failed tile does not fetch its file
  again. A PDF, PowerPoint or Word tile shows the JPEG of its first page that
  the server drew when the file was published (`thumbnail_file_id`, lazy), and
  its icon when it has none or the image fails. Other tiles show an image
  thumbnail or the file's icon. The first time the panel shows Files, by
  any route, every listed file counts as seen; a file published later shows
  Craft's new-file marker until the panel shows it, also as a new version
  in its open tab. Several files can be open at once; tabs switch
  with a click or the arrow keys, reorder by drag or Alt+arrow among the
  file tabs (on a touch screen, a swipe scrolls the strip and a press and
  hold starts the drag), and closing
  the active tab returns to the tab used before it, else to Files. Files and
  Sources cannot close or move, and a file tab cannot move before them. File
  tabs of one shown name show their paths. An artifact has one tab, which
  follows its newest version: a reload's list or a live publish of a newer
  version updates an open tab. A card of an older version, or an artifact
  link that names a version, pins the tab to that version, labelled "v{version} of {latest}"; the newest version has no
  label. A tab's name comes from the list, so a reload after a rename
  updates it, also on a pinned tab. The five most recent file viewers stay
  mounted, so switching back does not load the file again; a hidden one
  leaves layout (`content-visibility: hidden`). During a drag of the panel's
  edge, the content follows the width live, as in Craft, under an overlay
  so the pointer hovers nothing in it. A file tab and
  the preview modal show a file the same way: markdown as a document, a CSV
  or workbook as a grid with a sheet bar, a PDF one page at a time with page
  thumbnails and zoom, a PowerPoint deck one slide at a time with a slide
  list, a Word file as pages scaled to fit the width, an image fit to the
  panel, HTML as its page in a sandboxed frame, SVG as an image, and code,
  data and text as highlighted source with line numbers (plain text wraps
  instead). Markdown, CSV, HTML and SVG have a "Show source" button that becomes "Show preview" (an eye) on the source. The PDF and
  slide views share Craft's toolbar and resizable thumbnail column
  (`sections/file-preview/PreviewControls.tsx`). The column is one tab stop,
  the current page or slide, and the arrow keys move it, with focus. A
  preview under 480 px wide, as on a phone, starts with the column hidden:
  `lib/filePreview/hooks.ts:useThumbnailColumn` measures the row that holds
  the column and the page when it mounts, before the first paint, then
  follows its width until the user toggles the column. The modal shows
  the counts, copy, download and source toggle over the content's bottom. In
  the panel, the visible file's actions move to the URL bar's row through
  `PreviewActionsSlotContext` (`sections/file-preview/FloatingFooter.tsx`);
  the counts and an image's actual-size toggle stay at the bottom. A loader shows only when a load takes over 300 ms. A file over its
  format's limit (5 MB of text, 20 MB for Word or PowerPoint, 100 MB for a
  PDF), a legacy `.ppt` and other types show one card with a download
  instead. So does a failed load, with a retry, and a PDF, deck, Word file or
  image that does not render, such as a HEIC image.
  Closing the panel
  keeps its tabs, so reopening it, or coming back to the chat, restores them.
  A closed panel cannot be focused, and closing it returns focus to the
  control that opened it, or that last switched it from outside the panel,
  also when the panel covered the page.
  Escape leaves full
  screen first, before a run's Escape stops the run; a narrow page has no
  full screen, so Escape skips that step. Then it closes the active file's
  tab, back on its tile, or on the Files tab for a file without one, then
  closes the panel. Multi-model turns have no sandbox, so they publish no files.
- **A user rates, copies or shares an answer.** Copy turns markdown tables into
  tab-separated text so a spreadsheet keeps the columns. Each answer table
  also has its own copy button, which writes HTML with links and full source
  names (`lib/timeline/chat/message/tableCopyUtils.ts`). A share link opens a
  read-only copy. The page needs a session, so a visitor with none goes to
  sign-in.
- **A user shares or exports a chat.** The header's share button opens a menu
  with **Share…** and the two exports. Each chat's menu in the sidebar and on
  the project page has **Export As…** with the same formats
  (`web/src/lib/chat/hooks.ts:useChatExportMenu`). An export downloads the
  user and assistant turns as Markdown or plain text
  (`web/src/lib/chat/exportChatSession.ts`). The header hides the share menu in
  incognito.
- **A user deletes a chat** from its menu in the sidebar or on the project
  page; the header has no Delete. Deleting the open chat from the sidebar
  opens its project, or a new session when it has none
  (`web/src/sections/sidebar/ChatButton.tsx`).
- **The incognito start button** appears only on the new chat page when
  incognito is available and unlocked.
- **A user in incognito** cannot turn incognito on or off once the session
  exists, and answers show no rating buttons. Deep Research is unavailable. Leaving the chat, reloading or
  closing the tab ends it. If an explicit exit fails, an error shows and the user stays in
  the chat to retry.
- **When a send fails**, the partial answer stays and an error banner follows
  it. In a multi-model turn, only the failed panel shows the error. In a
  single-model send, a usage limit shows a banner with the reset time and no
  retry ([[rate-and-usage-limits]]).
- **After a failed answer**, the next message continues the conversation
  after it. The model sees the question and the saved partial answer. While
  the failed answer is the latest message, its banner offers **Regenerate**.
  It sends a new copy of the question as a sibling branch, and the failed turn
  moves to the hidden branch. After a later message, the banner has no
  **Regenerate**.
- **When the server rejects a send before it saves the question** (an HTTP
  error, a usage limit or a setup error, with no message IDs), nothing of the
  turn stays in the chat. The tree returns to its state before the send, the
  text goes back to the input bar, and the error shows below the chat with no
  **Regenerate**. A rejected regeneration keeps the earlier answer. A network
  failure without IDs can still have reached the server, so its turn stays in
  the tree. The next message follows the last saved message, so that turn
  becomes a hidden branch until saved history replaces it.
- **A developer who runs the web server in development** reaches the backend
  at `/api` on the web origin, streams included. A production web server
  answers that route with a 404 and a message that nginx must serve `/api`
  ([[#dev-api-proxy-only]]).

---

## Scope

This component owns:

- the `/app` page and its routes;
- the chat controllers: send, session load, feedback and multi-model;
- the per-session client store and the message tree;
- the client services that call the chat endpoints, and the stream reader;
- packet grouping and the timeline and answer renderers;
- the chat sections: input bar, sidebar, document sidebar and model selector;
- the incognito controls in the app chrome;
- first-run onboarding on the chat page, which uses the provider setup forms
  of [[llm-providers]];
- the development `/api` proxy route.

It owns the chat file previews; [[craft-frontend]] has its own previewers
for sandbox files.

Neighbours own the rest. [[streaming-protocol]] owns the packet vocabulary,
the enum mirrors, line framing and heartbeats. [[citations]] owns marker
resolution and the partial-link hiding inside the answer. [[core-chat-loop]]
owns the send, stop, resume and status endpoints, and [[chat-persistence]] the server
tree and replay. [[agents-personas]] owns `/app/agents`. [[plugins]] owns the
plugins page and the tools popover, and [[mcp-and-custom-tools]] the MCP
connection prompt. [[desktop-widget-extensions]] owns the Chrome extension's
new-tab and side-panel pages and framed sign-in.

---

## Architecture

Component, styling, i18n and data fetching rules for this code are in
`web/AGENTS.md`. This document does not repeat them.

```
AppInputBar -> useChatController.onSubmit           web/src/hooks/useChatController.ts
  implicit multi-model pick (if needed)             PUT set-preferred-response
  optimistic user + assistant nodes in the tree
  updateCurrentMessageFIFO                          app/app/services/currentMessageFIFO.ts
    sendMessage -> handleSSEStream -> withoutHeartbeats   app/app/services/lib.tsx
    FIFO.acknowledged resolves with the stream and its rows from the ID line
  drain loop, one store update per animation frame
    updateSessionMessageTree(frozenSessionId, ...)
  settleChatSession                                 web/src/lib/chat/settleChatSession.ts
    await ack and reader -> reattach a lost running stream, or
    waitForChatResponseEnd -> follow next stream or release input
AgentMessage -> usePacketProcessor -> processPackets   timeline/hooks/packetProcessor.ts
  groups by (turn_index, tab_index); builds citationMap, documentMap, stop state
  tool groups -> timeline steps;  display groups -> answer
  RendererComponent -> findRenderer                 renderMessageComponent.tsx
```

**The store.** `web/src/app/app/stores/useChatSessionStore.ts` holds a `Map`
of session data keyed by session id, plus `currentSessionId`. Each session has
its own message tree, chat state, `AbortController`, `sendAcknowledged` and
`readerFinished` promises, and display state. The server queue and session
status live in SWR (see Pending input below); the store has no copy of either.
The `AbortController` identifies
the request that owns the session; late work from an older request checks it
and stops. A stream keeps writing to the session that started it
(`frozenSessionId`), so a user can switch chats while one streams. Chat states
beyond `input`, `loading` and `streaming` include `cancelling` (Stop sent),
`unconfirmed` (the client could not confirm execution status or load saved history) and
`uploading` (attachments upload). `onSubmit` ignores a send unless the state
is `input`. Pending messages use a separate endpoint. They name the target
response when the client knows its ID; otherwise the server targets the running
response. They allow no new attachments and need an explicit choice for a
multi-model turn.
Each `setCurrentSession` runs `cleanupOldSessions`, which keeps at most ten
sessions in memory. It drops only idle ones: not current, in `input`, and
known not to be incognito (or still empty). Pending messages live on the server. An incognito chat cannot be
rebuilt from the server, so the tab holds its only copy. A dropped chat loads
from the server again when the user opens it, so state kept only in the store
does not survive it. Navigation goes through
`web/lib/opal/src/navigation/hooks.ts:Navigation.go`: it writes the URL with the
history API first, so the tabs follow the click, then asks Next to render a new
route, with `PendingRoute` showing the URL's loader meanwhile. Within `/app`,
`web/src/lib/navigation/hooks.ts:AppPosition` changes only the query, which
`AppPage` renders itself, so writing the URL is the whole switch; in-app links
use its `linkTo*` props. A send from a new session makes its chat current
before the URL changes, so a switch to a new session in that gap writes no new
URL; `openNewSession` and `linkToNewSession` clear the current chat for that
case. `AppChrome`'s `PendingRoute` loader is
`web/src/layouts/chromes/AppChromeLoader.tsx:AppChromeLoader`, which picks the
URL's page loader (the agents catalog, the agent editor, the page loader, or
blank for a view of `/app`). `/app/loading.tsx` re-exports it, so the same
loader shows while Next commits the route.

**The message tree.** `app/app/services/messageTree.ts` mirrors the server tree:
nodes keyed by `nodeId`, each with `latestChildNodeId`.
`getLatestMessageChain` walks it to get what the page shows. On load,
`app/app/services/lib.tsx:processRawChatHistory` builds the tree from the
session response and its replay packets ([[chat-persistence]]). Refreshing the
latest page preserves loaded history that connects to that page, unless an
older loaded reply still shows a waiting approval card: the latest page holds
every such reply, so that history is stale and is dropped. Incognito
recovery checks execution status and retains local content. A saved
failure becomes an `error` node with `errorMessage`, `errorCode` and
`isRetryable` from `error_info`; `message` holds only answer text.
Unless it edits, regenerates or makes an implicit multi-model pick, `onSubmit`
puts a new message after the last chain node that has a `messageId`, a saved
failed response included, and sends that ID as `parent_message_id`. The local
parent and the server parent are the same node. When the server answers
without admitting the send (`CurrentMessageFIFO.acknowledged` resolves to
`null`) or the send fails before dispatch, `restoreTreeBeforeSend` removes the
send's nodes and restores the links of their parent. The error goes to the
session's `uncaughtError`, a `SessionError` with the error code and details.
The reader returns a rejected send’s error when it finishes. Completion and
Stop both read that result before releasing the input.
An automatic follow-up response has a hidden `agent_results` question node as
its parent. `ChatUI` and the shared chat view render that node with
`web/src/lib/timeline/chat/message/AgentResultsDivider.tsx`, with no message controls. Checks that
look for the last `user` node skip it, and export omits it. A multi-model turn
is unresolved only while the chain tip's parent is its user message
(`web/src/lib/timeline/chat/message/multiModel.ts:getUnresolvedMultiModelTurn`), so a follow-up past it does not
reopen response selection.

**Packet processing.** `processPackets` is incremental. It processes only
packets past `nextPacketIndex` and keeps its state in a ref. It decides each
group's kind from the group's first tool or display packet, and keeps it: a
tool packet (`isToolPacket`), including image generation, makes a timeline
step. `MESSAGE_START` makes an answer group. Debug and control packets
that arrive first do not decide the kind. `buildGroupsFromKeys` drops a group with no packet in
`CONTENT_PACKET_TYPES_SET`. Citation and stop packets update state instead of
making their own step. Generated images accumulate across tool steps, unique
by file ID, and render once, inline right after the step that made them
(`web/src/lib/timeline/chat/message/messageComponents/AgentMessage.tsx:buildSectionSegments`), as soon as they arrive. An image
ends its step's run, so a later step starts a new run card. Later tool
calls do not hide them. An image call does not mark the answer as final;
later search or image calls can continue the timeline. Published files work the same way: each
`publish_files_end` adds its files, unique by file ID, to
`ProcessorState.publishedFiles`, and
`AgentMessage` shows them after the answer of their section once the section
ends: the response stopped and its answer rendered (`isComplete`), or a later
section began (`buildSectionSegments` owns the placement)
(`sections/chat/PublishedFileCards.tsx`, which downloads from
`/api/chat/file/{file_id}`; a click calls `PublishedFilesPanelContext`'s
`openFile` and the view-all button its `showFiles`, which the chat page
(`CHAT_FILES_PANEL`) and the shared view provide; without one, the card opens
`PreviewModal` and every card shows). An artifact link in an answer
(`{WEB_DOMAIN}/app/artifacts/<artifact_id>[/v<N>]`, which the artifact tools
give the model; `lib/chat/publishedFiles.ts:parseArtifactLink`, any origin)
calls the same `openFile` with the file that `GET
/api/chat/artifacts/{artifact_id}?version=N` gives
(`lib/timeline/chat/message/MemoizedTextComponents.tsx:MemoizedLink`), also a file of
another chat, pinned to the version that the link names. A response that
arrives after the user switched chats, or after a later artifact link click, opens nothing. A modified or middle click, or a page without the panel, keeps
the link's new tab. The route `app/app/artifacts/[...link]`
(`sections/chat/ArtifactLinkPage.tsx`) resolves a link outside a chat by the
metadata route's `access`: the `owner` goes with `artifactId` and
`artifactVersion` to the owning chat, a `chat_reader` (a public share) to
the chat's shared view (`app/app/shared/[chatId]`), and `file_only` (a
version that a chat the user can read holds, such as a reader of another
chat whose replace added it; only a link with `/v<N>`) shows the file alone
with `PublishedFilePreview` and `DownloadButton`, with no chat. A response
that arrives after the user left the link's URL sends the user nowhere.
`lib/chat/hooks.ts:useOpenArtifactFromUrl` (on the chat page and the shared
view) opens the version once the chat has loaded, pinned when the URL names
a version, then drops the parameters. Any other user gets not-found. `parseArtifactLink` and the
backend's `parse_artifact_url` read the same example links
(`backend/tests/unit/onyx/tools/sandbox/artifact_links.json`).
The right panel (`sections/chat/ChatRightPanel.tsx`)
is built from the output-panel parts that it shares with Craft's panel
(`sections/output-panel/` and `lib/outputPanel/`): the presentational parts,
the tab rules, and `sections/output-panel/PanelResize.tsx:useOutputPanelWorkspace`, which measures
the workspace, resizes the panel, makes the covered page inert after it moves
focus out, and restores a full panel on Escape. [[craft-frontend]] lists the
parts, and a change to them changes Craft's panel too. A file tab and
`PreviewModal` show a file through `sections/file-preview/FilePreview.tsx:FilePreviewBody`,
with one renderer per format in `sections/file-preview/`. Each loads the file
with `lib/filePreview/hooks.ts:useChatFilePreview`, an SWR read that
`FilePreviewScope` scopes to the preview, so the file's bytes go and its
download stops when the preview closes, and that does not revalidate. A
file tab keys the scope by the shown file, so a tab that moves to another
version starts a new preview with fresh controls.
`FilePreviewBody` owns the card for a file that cannot show; a renderer only
reports that it failed. Its loader,
`lib/filePreview/loadChatFilePreview.ts:loadChatFilePreview`, reads
`/api/chat/file/{id}` once with the default cache mode. The response's name
and type pick the format (`lib/filePreview/format.ts:resolveFilePreviewFormat`).
A spreadsheet reads the server's parsed sheets (`?parsed=true`) instead of
the workbook, and an image or an unsupported file reads no body: the image
loads from the file URL in an `<img>`. SVG loads as text, because the server
serves it as `application/octet-stream`, and renders from a `data:` URL. HTML
renders through `srcdoc` with an empty `sandbox`: an opaque origin with no
scripts, so it cannot reach Onyx's page, cookies or API, and the sandbox
refuses a meta refresh. A fixed prologue (`<!DOCTYPE html>` and a CSP meta)
that `sections/file-preview/FilePreview.tsx` puts before the file also sets
`script-src 'none'` and stops every network load: the page shows only its
inline styles and its `data:`/`blob:` images, fonts and media, so it cannot
send the file's contents to another site. Scripted or CDN parts do not show. Decision: scripts
and CDN loads come back only with a real browser surface for previews, not by
loosening this policy; the page's CSP applies too. Other bodies
are read up to the format's limit while they stream, because the server sends
no length. Text over 200,000 characters shows without highlighting, and
markdown over it shows as source. Nothing makes an object URL. PDF.js loads only for a PDF, from
the build's `/pdfjs/` assets, with `isEvalSupported` off. A Word file renders
through `lib/docx/renderDocx.ts`, which sanitizes it, into a shadow root. A
PowerPoint deck parses in the browser with `@jvmr/pptx-to-html` through
`lib/pptx/renderPptx.ts`, which sanitizes each slide: no script, no style
element, and no image or CSS `url()` from outside the deck: a style property
with any `url()` that is not an embedded image goes. Each slide
renders into its own shadow root, scaled from the deck's slide size. The
parser uses namespaced selectors that jsdom lacks, so Jest tests give its
output.
Markdown shows raw HTML as text. Craft's previewers read sandbox paths, not
chat files. Published files belong to the chat, not to a branch.
`lib/chat/publishedFiles.ts:chatPublishedFiles` owns the Files list: the
newest load's `published_files` (the newest version of each artifact, by
the artifact's first publish), then the files that packets published after
the loads, such as live publishes and an answer that resumes after an
approval, merged per artifact (`artifactKey`) into its highest version. A
file saved without `artifact_id` is its own one-version artifact. The
session's `loadedPublishedFiles` holds the list, the sequence of the load
that gave it, and the file IDs that the list covers: the files that the
loads' packets replayed, and the files that the chat's packets held when a
load with a list started (`addLoadedPublishedFiles`; every load and settle
applies the `ChatLoad` that it took as its fetch started, and an older page
adds its packets). A covered file that the list leaves out stays out: an
older version, a deleted file, a file saved without an artifact or one whose
object is missing. So a live publish on a message that a reload's page
leaves out does not come back after a delete. Without a list, the packets give all the
files. A version that the chat added to another chat's artifact (its
`chat_id` is that chat) stays out, as the list leaves it out; its reply
card shows it.
A shared chat has no live publishes, so its load's list alone gives its
files, until the panel's reload adds a newer page's list. A file tab (`ChatRightPanelState.fileTabs`, keyed by
`rightPanelFileTab`, the artifact) keeps the file that it opened with and
whether it is pinned: both panel openers (`openPublishedFileInChat`, the
shared view's opener) build the action with `openCardFileAction`, which
pins it when an artifact link names the version (`pinVersion`) or the chat's
files hold a newer version (`newestVersion`). A card
saved without `artifact_id` whose file the list holds opens the listed
file, so the card and its tile share one tab. The panel shows a pinned tab's file, else the newest
version of its artifact, so a card always opens its own file, also one that
the list does not hold. A background
subagent's files are not in the root stream; they appear at the next
latest-page load, for example when the turn that its results start settles.
Foreground subagent publishes stream nested in the root answer.
`lib/chat/hooks.ts:publishedFilesOf` builds a chat's files once per message
tree and loads, for the open chat and the shared view; `usePublishedFiles`
keeps them the same while their content does, and the panel and its views
are memoized, so a packet that changes no file or tab does not render the
panel.
`views/AppPage.tsx` puts a memoized `CurrentChatRightPanel` element in the
app shell's right slot, as the shared view places `ChatRightPanel`. Both
always mount it, so a card opens its file also when the list holds no files;
closed, the panel takes no room. The panel draws its own toggle once the chat
has a session, and the header leaves room for it at its end
(`layouts/chromes/AppChrome.tsx`, the shared view's header padding). That room
is `--panel-toggle-reserve`, a registered property in `app/globals.css`: the
open panel sets it to zero on the page element, and the page eases it with
the panel's slide. The size button's `end-12` in
`sections/chat/ChatRightPanel.tsx` repeats its 48px initial value; change both
together. In the
DOM, the toggle follows what the user sees: a closed panel puts it in the
workspace's `panelToggleSlot`, before the page, and an open panel puts it
before its tabs. Closing gives focus back to it when the move or the panel
took focus. The
element changes only with its inputs (open, the Sources view, whether
Sources has content), so a packet, a search keystroke, a tab change or a
resize renders the panel and not the app chrome. Names that the model or the
sandbox chose show in their own text direction: the tab strip and the tiles
isolate them with `dir="auto"`, an older version's tab puts the name in a
`<bdi>` apart from its sentence, and the URL bar and a card show a path with
`dir="ltr"` (a card's path is an Opal code span). In the panel, cards and
Files search, a published file's shown name and path come only from
`lib/chat/publishedFiles.ts:publishedFileLabel` and `publishedFilePath`, which
strip bidi controls. The timeline step shows the sandbox path from the start
packet, stripped where it renders.

The panel's state and its transitions are one pure module,
`lib/chat/rightPanel.ts:rightPanelReducer`, which owns the tabs: the mode
(closed, medium or full, as Craft's), the open files (Files and Sources
are fixed tabs, so only the active tab and the history name them), width,
search and seen files. The Files list and the file tabs follow the shared
tab rules (`lib/outputPanel/tabs.ts:openPanelTab`, `closePanelTab`), with
the Files list first, so closing the last file tab shows the Files list;
Sources stands apart. A file that the panel shows counts as seen
(`markSeen`); the first time the panel shows files, the panel marks the
listed files seen once (`initializeSeen`). The store keeps one state per
session and applies the reducer (`updateCurrentRightPanel`); the shared view
applies it with `useReducer`. The store keeps each chat's width in session
storage (`lib/outputPanel/preferences.ts`, which Craft's preferences also
use), and every load of a chat applies its approvals version and published
files in one place (`app/app/stores/useChatSessionStore.ts:applyLoadedSession`). The panel shows one tab at a time. A move
(`reorderTab`) names the tab that it drops on. The automatic close
(`hideSources`) closes the panel only when Sources is active. The panel lives
in the app shell's right slot.
`layouts/chromes/AppWorkspace.tsx` gives it the workspace row and the page
column; the open panel measures the row, so a width change renders the panel
and nothing else, and a covering panel makes the page column inert. A closed
panel does not watch the width; it measures again when it opens.
`ChatSidePanel`'s `reserve` keeps the medium width in the row's flow, and the
panel sits over the row's end: at the reserve's width at medium size, at the
row's full width (`100%`) when it covers. A change of size moves only the
panel's edge, never the page or the panel's position. The width slides only
when the panel's shape changes (open, close, beside or over the page); a
change of the row's width or a drag applies at once. The panel and its
reserve carry transition timing only while they slide: CSS
`transition-property` defaults to `all`, so a duration left on them animates
every drag step and the panel trails the pointer. The chat panel throws
without the workspace context.
In the panel, `sections/document-sidebar/DocumentsSidebar.tsx` gets no
`closeSidebar` and draws no frame; NRF draws its frame. `sections/chat/ChatSidePanel.tsx` is
the sliding panel frame: it returns focus to the opener on close. It records
the opener in a layout effect, before the covering panel's layout effect
moves focus to the panel toggle. The chat
page and the shared view use it only through `ChatRightPanel`; NRF uses it
directly for its Sources panel. Focus moves into the panel only when it opens from
outside (a card, a citation, the panel toggle); a card focuses the file's
preview, also when it opens another version of the shown artifact. A
tab-strip change keeps focus on the strip, and so does a new version that an
unpinned tab follows.

A group closes on its own parent-level `SECTION_END` or `ERROR`
(`lib/timeline/chat/packetHelpers.ts:isGroupEndPacket`,
shared by `isToolComplete` and the packet processor); a new `turn_index` or a
stop packet adds a parent-level `SECTION_END` to each open group. A stop
packet also ends each open nested call, because no packet follows it. A code
mode final delta with any status but `running` ends the open nested calls of
its group the same way: the backend sends no end packet for a call that the
cell's end cut off, so the call renders as stopped. A command whose
`exec_end` has `completion` `canceled` (Ctrl-C through `write_stdin`)
renders as Canceled. Parallel
tools share a `turn_index` and differ by `tab_index`. The child packets of a
subagent or a code mode program
carry the parent's key plus `sub_turn_index`, so they join the parent group,
and their `SECTION_END` or `ERROR` does not close it. A nested `MESSAGE_START`
does not start the answer.
The packet processor splits each group once
(`lib/timeline/chat/hooks/packetProcessor.ts:buildGroupsFromKeys`).
`GroupedPacket.packets` holds only the group's own packets. The step-kind checks
in `lib/timeline/chat/packetHelpers.ts`,
`findRenderer`, the header, and `isToolComplete` read only these, so a research
step with a nested search is a research step, not a search step.
`GroupedPacket.nestedCalls` holds the nested calls, made with
`lib/timeline/chat/packetHelpers.ts:nestedCallSnapshot`.
Each `NestedCall` holds one call's packets placed at parent level, so the tool's
own renderer reads it as a direct call. The snapshot reuses the object of each
unchanged call, so memoized renderers of finished calls do not redraw.
`ResearchAgentRenderer` draws each entry of `nestedCalls` with the renderer of its tool.
After the answer starts, a tool packet of a group whose tool has not started
is a new tool call and sets `finalAnswerComing` back to false. The tool starts
with its first tool packet other than a pre-start packet
([[streaming-protocol]]), so a call whose
arguments streamed before the answer also counts when it starts. A later
packet of a started tool, such as a code mode closing record, joins its group,
and the answer stays shown. The stop packet sets `finalAnswerComing` again
when the latest display group is text, not a user message. Nothing follows the
stop, so the text of a step that ends the response with a tool call, such as
`wait_agent`, is the answer. A cancelled or failed turn shows its latest text
the same way, as its saved answer does. Live,
the closing record follows the answer. On replay, it follows its tab's section
end, before the answer's `message_start`. Both orders give the same groups.
The mobile app copies the group end and step-kind rules in
`mobile/src/chat/timeline/packetHelpers.ts` and
`mobile/src/chat/messageProcessor.ts` ([[mobile-app]]); change both. Its
`GroupedPacket.packets` also holds only the group's own packets. Mobile has
`nestedCalls` for code mode steps.

**Code mode steps.** Code mode runs behind the scenes: the timeline shows the
tool calls a program makes, not the program.
`lib/timeline/chat/transformers.ts:expandCodeModeSteps`
turns each nested call of a run or wait group into its own
step, drawn by that tool's renderer as a direct call would be. The packet
processor adds each nested packet to its call as the packet arrives, and after
each processed batch builds `GroupedPacket.nestedCalls` for each group with
`lib/timeline/chat/packetHelpers.ts:nestedCallSnapshot`.
It reuses the `NestedCall` object of each unchanged call, and
`expandCodeModeSteps` reuses the step it made for that object, so memoized
renderers of finished calls do not redraw. A call is its cell and
`sub_turn_index`, as `CodeModeRenderer` (`backend/onyx/chat/renderer.py`)
states, so the latest report replaces the earlier ones in place. Pacing
compares the last packet of each step, because a new report can have as many
packets as the old one. The program, its output, wait tool (`wait` or `poll`)
calls, yields and closing records have no step. A program without tool calls
shows no step. `expandCodeModeSteps` returns the steps and `codeModeWorking`
in one pass: a program runs from `code_mode_start` until a `code_mode_delta`
reports a status, and a running program whose cell has no running call sets
it. A yield (status `running`) ends the program's turn: the model acts next.
`useTimelineHeader` takes `codeModeWorking`, so the run header reads
"Working" while the program runs between calls.
The header names a step's activity from its own first packet; nested packets
do not decide it. A step with no activity of its own reads "Working". A
command step names its program (`web/src/lib/timeline/chat/commandProgramName.ts`, from T3 Code).
A reasoning step shows the title of its latest section, a bold line or a
heading (`reasoningPreview`), or "Thinking" before the first title. Its own
step card also shows this title while it streams. The
collapsed run card shows this header while it works. Once done, it reads
"Worked for {duration}", or "You stopped after {duration}" when the stop
ended its work. Only the response's first run uses the response's start and
duration (`isFirstRun`); a later run times itself. Before
the first step, the response shows the cursor, not a run card. `TransformedStep.groupKey` keeps the packet group of a step,
so pacing still knows restored steps. The expanded timeline renders one list
keyed by step (a parallel group by its first step), not by position, because a
cell's new call can move later steps into another turn group. The rail
primitives, `RunStep` and that list (`TimelineSteps`) live in
`web/src/lib/timeline/`, which Craft shares ([[craft-frontend]]).
`web/src/lib/timeline/chat/transformers.ts:groupStepsByTurn` gives every
step its own group, in turn order. Concurrent calls of one program show as
sequential steps, not parallel tabs: on replay the backend emits each call's
packets one after another, and the saved calls have no start or end order, so
the client cannot tell which calls overlapped. Mobile mirrors these transforms
in its own module, `mobile/src/chat/timeline/transformers.ts`, so change both;
its tests mirror the web cases. Mobile processes all packets again on each
flush, so it does not reuse call or step objects.

**Resume.** `web/src/hooks/useChatSessionController.ts` loads the session.
When the response has `current_stream`, Stop can target that stream at
once. `current_stream` is a `ChatStream`: the stream ID and the
`response_ids` of the rows it writes, in model-index order. The stream ID is
not a message ID; a continuation after approvals gets a new one. A send's
acknowledgement gives the same shape. `lib/chat/settleChatSession.ts:prepareSavedChat`
turns the saved page and the local tree into the tree to show and the stream
to replay; load, `refreshChatSession` and `followChatStream` use it. Each row
keeps its `replay` position with the stream ID it belongs to.
`prepareSavedChat` keeps the local rows only when their `replay` belongs to
the same stream; other rows reset, and the stream replays from cursor 0.
`lib/chat/settleChatSession.ts:followChatSession` calls `resumeStream` with
the stream ID and that cursor. In a multi-model turn it routes each packet to
the row at `placement.model_index` in `response_ids`, and gives the overall
stop to every answer. It publishes packets only at each `StreamCursor` line, so the cursor
and the packets it covers are stored together
([[streaming-protocol#buffer-gap-ends-resume]]). It holds the backlog until
`replay_complete`, and marks it with `restoredPacketCount` so that
`AgentMessage` shows it without animation. `resumeStream` does not drop
heartbeats, so `followChatSession` drops `chat_heartbeat` itself, and the
`replay_end` marker of a continuation stream. A resumed
error packet turns its answer into an `error` node. The backend decides whether
queued input can run. When
the reader ends, it settles the session.

When the user opens a session, it is fetched again when its state is
`input` or `unconfirmed`, or its `AbortController` is aborted. In the last two
cases the load recovers: it
merges the local tree into saved history (`preserveFailedMessages`, or
`app/app/services/messageTree.ts:restoreIncognitoMessages` for incognito,
which maps saved ids onto local nodes), resumes, and settles in `recovery`
mode. An `onSubmit` path that returns without settling must leave the session
in one of these states, or it stays busy.

**Settlement.** `web/src/lib/chat/settleChatSession.ts:settleChatSession` is
the only path back to the `input` state after a send, a Stop or a resume
([[#settle-before-input]]). It waits for the send acknowledgement and the
reader. If the reader ended without a stop or marked its answers
`streamLost`, settlement waits one poll interval and reads `/status`. When
the same stream still runs, it attaches a new reader to it through
`prepareSavedChat` and `followChatSession`: from the rows' `replay` cursor,
or from cursor 0 into reset rows when the send stream had no cursor. The store keeps the received rows until the replay publishes its first
batch, so an unavailable replay loses no output. Only a 404 from
`resume-stream` passes `streamUnavailable`; settlement then does not reattach
to that stream, because it has no buffer. A network error, a 5xx, a 429 or an
end before the first cursor reattaches after the next status read; a 401 or
403 surfaces through the failed status read. Otherwise
`lib/chat/sessionReadiness.ts:waitForChatResponseEnd` polls `/status`
until that response releases ownership, and returns the current stream of
the turn that owns the session next. A queued response can take ownership
without making the session idle; `refreshChatSession` loads the latest page
and `followChatSession` attaches to it. An incognito chat loads no history: it
follows a next stream whose answers it has, such as an approved answer's
continuation, with `followChatStream`, and waits through other turns. `refreshChatSession` runs only when no reader owns the session: when
settlement finds a next stream, or when a status read shows an idle chat a
running turn or a latest response it does not have. Readiness polls write each
status into the SWR status cache, so `lib/chat/hooks.ts:useChatSessionQueue`
sees every status read; a changed `latest_response_id` also reloads the
pending list.
Overlapping calls from one session owner share one in-flight refresh; a newer
owner starts its own. A refresh drops its result if a new send replaced the
session's `AbortController`, or a reader such as a continuation took the
session (`readerFinished`). Refresh and
settlement merge saved pages through one function that keeps local failed
turns and remaps the selected response.
After a resume, a Stop, an error or a failed save it also reloads saved
history. `preserveFailedMessages` keeps a local error unless the saved row's
`response_status` is `complete`, `limit`, `cancelled` or `suspended` (text
or files when the field is absent), so a parked answer shows its saved
waiting requests. It keeps the local `streamLost` mark only while the saved
row is `running`. After a clean send, the streamed tree stays. Settlement
never reloads the whole history of an incognito session, in either record
mode. On a reload or recovery, each answer of the latest turn
(`getLatestTurn`) that lost its stream, and each answer of a named stream
that this browser could not read (it ended first, or its resume failed
before its first batch with content), takes its saved copy if the
server parked it or the saved copy asked for approval (`savedAnswers`; only a
chat that saves content parks an answer or asks).
Each other lost answer gets a stop packet if it has none, and loses its
`streamLost` mark. A failed or timed-out (10 s) readiness request sets `unconfirmed`.
A newly active stream during reload transfers to the same replay reader. Recovery comes
from the input bar's manual check or from loading the session again (see
Resume).

**Pending input.** `lib/chat/hooks.ts:useChatSessionQueue` holds the pending
list and session status in SWR. `useChatSessionController` mounts it once per
chat page and passes it to `AppInputBar`, which only renders it. The hook
subscribes to primitives and memoizes its result, so streamed frames do not
re-render the memoized `AppInputBar`; submit reads its target response from
the store when it runs. Incognito chats and anonymous users get a disabled
queue. One pending-message request runs at a time, and its cache writes use
the key of the chat that made it. Each request revalidates session status when
it ends, so polling starts for input it made startable. Submit appends the
accepted message, then revalidates, because a turn can take it at once. The list does not poll. A turn reloads it
once, when the status shows a new `latest_response_id` for the same chat: the
server takes a queued input in the transaction that starts its response.
Input that joins a running response arrives as a `user_message` packet;
`app/app/services/lib.tsx` removes that ID from the cached list on either
reader, with no request. Saved replay emits the same packets from each step's
human inputs, so both paths render user bubbles between response sections.
Status polls every 2 seconds while `has_startable_input` or
`has_active_subagents` is true. `stopSubagents` posts
`/api/chat/chat-session/{id}/stop-subagents`, then revalidates status.
The header's activity button (`sections/chat/ChatActivity.tsx`) shows once a
chat has a waiting request, a background agent or a published file. It is
always the icon alone, so the header never shifts, and toggles a card that
stays open until that button closes it. The card portals into the page column's
`activitySlot` (`layouts/chromes/AppWorkspace.tsx`) and pins under the header
at the chat region's top end, so the header keeps its width and buttons. With
no output panel open it sets `data-activity-docked`, and in a workspace at
least 64rem wide (`@container/workspace`) the chat's scrolled content, the
input row (`data-activity-room` in `views/AppPage.tsx`) and the footer make
room for it: at least its 1rem end gutter, plus what the gutter of the
centered chat column
(`--app-chat-column-width`, reading or wide) lacks, so on a wide screen the
column does not move, while the scroller keeps its width so its scrollbar stays at the
end; otherwise it floats over the chat's end. The header's left side
shows the chat's title on one clipped line; with no center content it takes
all the room before the buttons. A waiting row nudges its card into view; the Files row opens the right
panel. Agents come from
`GET /chat/chat-session/{id}/agents` (`lib/chat/hooks.ts:useChatSubagents`),
which reads `load_session_agent_metadata` for the selected branch and keeps
the `spawn_agent` children (`ChatConfiguration`; Deep Research workers are
foreground): `id`, `path`, `status` and `stopped_by_user`, with no
transcript. The list loads again when the status changes
`has_active_subagents` or `latest_response_id`, and polls while agents are
active. The status it reads also polls while a reply streams, so agents that
the reply starts show. An idle chat that sees a running or unknown
response refreshes history and attaches to the stream.
`app/app/stores/useChatSessionStore.ts:useCurrentResponseStopped` is true once
the latest response's last packet is a turn-level stop. `AppInputBar` then
hides Stop and treats the response as finished, since a Stop would reach the
finished stream while the server starts the next queued turn. The keyboard
highlight in `hooks/useQueuedMessageNavigation.ts` is keyed by message ID, so a
message that leaves the queue drops the highlight. `sections/input/inputBarKeys.ts`
ignores keys during IME composition.

**First-run onboarding.** `AppPage` renders
`web/src/lib/onboarding/components/OnboardingFlow.tsx`, and
`web/src/lib/onboarding/hooks.ts:useShowOnboarding` decides whether it shows.
The welcome screen shows a loader until `isOnboardingResolved` is true, so it
mounts once in its final layout. A saved dismissal resolves the decision at
once. Otherwise the hook waits until the provider and chat session requests
stop loading; a failed request also stops loading. While onboarding shows,
the grid's bottom row is a fixed 30% of the page, so steps grow upward and the
input's place does not depend on the previous layout or the load order.
The step order is in `web/src/lib/onboarding/constants.ts:STEP_CONFIG`.
Dismissal and an admin's saved step live in `localStorage`, keyed by user id,
so another browser starts again. The input lock is a comparison against
`STEP_CONFIG[OnboardingStep.OptionalSetup].index` in the input bar's
`disabled` prop in `AppPage`; a change to the step order must keep it.

**Action preference.** At send time `onSubmit` filters the selected Action through
`web/src/lib/tools/chat.ts:effectiveChatPreference`, which keeps a built-in
tool of the agent, else a saved integration action whose integration is on. Sending a message
preserves the selected preference for later messages in that chat. Each request
sends the current eligible selection, except Deep Research requests send no
preference. A preference does not restrict which available tools may run.
[[plugins]] owns Action availability.

**The development `/api` proxy.**
`web/src/app/api/[...path]/route.ts` forwards every method under `/api` to
`INTERNAL_URL` with the `/api` prefix removed. It passes the request body as a
stream, forwards each `set-cookie` header, and returns redirects to the
browser. For a streamed response it turns off caching and proxy buffering, so
packets reach the client as they arrive. In development, `DEBUG_AUTH_COOKIE`
adds an auth cookie so a local web server can call a remote backend. More
specific routes under `web/src/app/api/` take precedence over this one.

---

**The sidebar.** `web/src/sections/sidebar/AppSidebar.tsx:AppSidebar` shows
its header tabs and section titles at once. Each section (agents, projects,
recents) shows Opal's `SidebarLoader` until its own data loads, so a fast
section does not wait for a slow one; `usePinnedAgents` stays loading until the
user's pins are in its list. Folded, the header keeps the unfolded button
order. The header is
`web/src/sections/sidebar/BrandedSidebarHeader.tsx:BrandedSidebarHeader`, which
the admin and Craft sidebars share: the logo mark and the wordmark from
[[whitelabelling-and-theme]], and the fold button, which moves with the
column's edge as the sidebar folds. A sidebar renders it rather than setting
up its own branding.

**Run status on chat rows.** Each chat row (`sections/sidebar/ChatButton.tsx`)
shows live status from the session store and unseen Done or Failed status
from a separate store. The tooltip shows the title and status. Working shimmers
the title (`SidebarTab` `loading`). The other statuses put a mark at the row's
end. On hover, the options button replaces the warning icon, error icon, or
blue unseen dot for Done. Working (`loading`, `streaming` or `cancelling`), Needs
approval or Question waiting (`lib/chat/runStatus.ts:liveRunStatus`, from
`readWaitingToolRequests`, less the requests that this client decided), and
Failed or Done for a run that ended while its chat was not on screen.
`lib/chat/hooks.ts:useTrackChatRuns`, which `AppSidebar` mounts, watches the
store for runs that stop working and records Failed or Done in
`useUnseenRuns`. Tab storage keeps the 50 newest records across reloads.
Opening or deleting the chat clears its record. Signing out clears all records.

## Contracts and traps

1. `packet-list-append-only` **A message's packet list grows by appending,
   or is replaced.**
   `lib/timeline/chat/hooks/usePacketProcessor.ts:usePacketProcessor`
   processes only the packets past `nextPacketIndex`. It starts again when the
   `nodeId` changes, the list gets shorter, or the packet at the last processed
   index is a different object, as after a replay or a reload. So append to the
   same packet objects, and give a rebuilt list new ones.
   `lib/timeline/chat/message/messageComponents/AgentMessage.tsx:AgentMessage` memoizes
   on `packetCount` and the array, because a send mutates its array in place.
2. `packet-type-web-sets` **A new packet type needs more than an enum entry.**
   [[streaming-protocol]] lists the hand-mirrored places, including
   `findRenderer`. The web client keeps more hand-written sets that switch on
   `PacketType`, such as `app/app/services/packetUtils.ts:isToolPacket` and
   `lib/timeline/chat/hooks/packetProcessor.ts:CONTENT_PACKET_TYPES_SET`.
   To find all of them, run
   `git grep -l 'PacketType.FILE_READER_START' web/src`. Run it again for a
   type that behaves like the new one. Add the new type where a similar type
   appears. If an entry is missing, the packet renders as
   nothing, or as a generic step, and nothing logs an error
   (`RendererComponent` returns an empty block).
3. `background-keeps-current-session` **Only the active view may move
   `currentSessionId`.** `updateSessionAndMessageTree` in
   `web/src/app/app/stores/useChatSessionStore.ts` sets `currentSessionId`.
   Code that runs in the background, such as a resume tail, must check that
   its session is still current or use `updateSessionMessageTree`. Otherwise
   it takes over the chat the user moved to, and their next send goes to the
   wrong session.
4. `stop-does-not-abort-fetch` **Stop does not abort a dispatched fetch.**
   `web/src/lib/chat/stopChatSession.ts:stopChatSession` sets `cancelling`,
   waits for `sendAcknowledged`, posts `stop-chat-session` with that stream ID
   (the assistant message id, or the user message id for a multi-model turn),
   and then settles. The reader stays open to receive the final packets. Only
   a Stop before the send is dispatched aborts, with the reason
   `STOP_BEFORE_DISPATCH`; `onSubmit` then removes the unsent turn and puts
   the draft back. A failed stop request returns the session to `streaming`.
   A rejected acknowledgement leaves it `unconfirmed`, and a `null` one sends
   no stop request and only settles. A `pathname` change also aborts (the
   cleanup effect in `web/src/hooks/useChatController.ts`); a chat switch
   inside `/app` does not. That abort only detaches the reader: the server turn
   continues, `onSubmit` returns without settling, and the next load of the
   session recovers it.
5. `fifo-abort-records-error` **The FIFO records an abort as an error.** In
   `app/app/services/currentMessageFIFO.ts:updateCurrentMessageFIFO`, an
   aborted send sets `stack.error` to `"AbortError"`. The catch block in
   `onSubmit` returns on `controller.signal.aborted` or lost stream ownership
   before it builds error nodes, so an abort renders no error node. Make the
   same check in any new consumer of the FIFO before it turns `stack.error`
   into UI.
6. `server-owns-queue` **Only the backend starts queued turns.**
   `sections/input/AppInputBar.tsx:AppInputBar` submits text through
   `useChatSessionQueue`. It does not wait for rendering or call normal send
   when a response ends. SWR owns the pending-list cache. Accepted between-step
   inputs use the same ordered packets for live display and reload. A failed
   POST returns the text to the composer, ahead of any text typed since, or to
   that chat's draft when the chat is no longer open. Editing waits for DELETE to
   return the withdrawn text and makes that chat's composer read-only
   meanwhile, so typed text cannot collide with it. If the user switched chats
   during the request, the returned text goes to the original chat's draft. A conflict refreshes the list without
   restoring text that was already accepted.
7. `branch-switch-reaches-server` **A branch switch must reach the server.**
   `web/src/hooks/useChatSessionController.ts:onMessageSelection` updates the
   local tree and calls `app/app/services/lib.tsx:patchMessageToBeLatest`. The
   backend accepts a send only when its parent is on the server's active branch
   ([[chat-persistence#send-parent-on-active-branch]]), and a reload shows the
   server's branch. A UI path that changes `latestChildNodeId` without the PUT
   breaks both. After selection succeeds, refresh session status: an idle
   branch has no polling timer to discover another branch's active children.
8. `implicit-pick-revertible` **An implicit model pick must be revertible.** A
   follow-up to an unpicked multi-model turn picks the most visible answer,
   applies it locally and PUTs it. `web/src/hooks/useChatController.ts:onSubmit`
   waits for that PUT before dispatch. If it fails, the send fails: only the
   preference is cleared, so a retry runs the PUT again; a newer explicit
   pick is kept. The send's nodes go away and its text returns to the input
   bar. A Stop while it waits is a before-dispatch abort.
9. `usage-limit-is-packet` **A 429 usage limit is a packet, not a throw.**
   `app/app/services/lib.tsx:sendMessage` turns it into a `StreamingError` with
   `is_retryable: false` and no `model_index`, so in a single-model send the
   banner renders through the normal error path. A multi-model send drops it
   (see Known issues). The response shape is owned by
   [[rate-and-usage-limits]].
10. `incognito-toggle-locks` **The incognito toggle locks once a session id
    exists.** The mode is pinned when the session is created, so an empty
    session that is reused keeps its mode.
    `app/app/services/lib.tsx:createChatSession` throws when an
    incognito create comes back without `incognito: true`, because an old API
    server pod in a rolling deploy does not pin the mode. Leaving an incognito session calls
    `endIncognitoSession`; closing the tab sends a `sendBeacon` on `pagehide`.
    When both fail, the server sweep cleans up ([[chat-persistence]]).
11. `chat-url-drops-ids` **`app/app/services/lib.tsx:buildChatUrl` drops
    `PARAMS_TO_SKIP`.** Chat, agent and project ids are never carried over
    from the old URL. `views/AppPage.tsx:AppPage` removes
    `projectId` when `agentId` is also present, because an agent pick replaces
    project context.
12. `dev-api-proxy-only` **The `/api` route handler serves development only.**
    `handleRequest` in `web/src/app/api/[...path]/route.ts` returns 404 unless
    `NODE_ENV` is `development` or `OVERRIDE_API_PRODUCTION` is `true` (for
    preview environments). In production, nginx strips `/api` and forwards to
    the API server (`deployment/data/nginx/app.conf.template`). A fix to
    streaming, cookies or redirects in this file does not reach production;
    behaviour that works through it in development must also hold behind
    nginx.
13. `settle-before-input` **Only settlement returns a session to `input`.**
    A stream that ends does not mean the turn is saved
    ([[streaming-protocol#stream-end-is-not-idle]]). Do not set `input` when
    the reader ends; call `settleChatSession`. The server admits one turn per
    session until execution and storage drain, so an early send gets a 409
    ([[core-chat-loop#session-admission]]). Each step re-checks that the
    session's `abortController` and `readerFinished` are still the ones it
    started with, so a late settlement cannot overwrite a newer request;
    session load makes the same check after each await. The send
    acknowledgement decides what is safe. It resolves with the stream (its ID
    and response rows) on the ID line, or with `null` when the request ends without one (a 4xx
    other than 408, which `app/app/services/lib.tsx:sendMessage` throws as
    `ChatSendRejectedError`, or the usage-limit packet). It rejects only for a
    5xx, 408 or network failure before the ID line; after that only a
    `recovery` settlement can return to `input`.
14. `group-packets-false-lead` **False lead:
    `app/app/services/packetUtils.ts:groupPacketsByTurnIndex` has no
    production caller.** Grouping happens in `processPackets`
    ([[#packet-list-append-only]]).

15. `scroll-follow-intent` **The user's input sets the scroll mode; layout keeps it.**
    `lib/chatScroll/components/ChatScrollContainer.tsx` is in one of three
    modes: `following` keeps to the end as content grows; `reading` never moves
    (native scroll anchoring keeps the content still); `gliding` is its own
    smooth scroll to the end (a send, the button), which ends on `scrollend` or
    a timeout. A scroll event is the user's only within 600ms of scroll input
    (wheel, touch, scroll keys, a focus move into the view), or while a pointer
    is held on the view; each such move restarts the 600ms, so a fling stays the
    user's while it moves. Then the position sets the mode. A glide ignores
    input from before it started, and a send's glide stops at the user message
    of a turn taller than the view, which then reads. A move that keeps the
    distance from the end is native anchoring, not the user, even with a
    pointer held. Any other move is layout (Firefox clamps the
    position while content briefly shrinks, anchoring adjusts, a glide runs),
    and only a `following` view reacts, by returning to the end. The one
    exception: with auto-scroll off while a reply runs, growth that leaves the
    end makes the view `reading`, so a later resume never jumps. A change of
    the chat's width, such as the right panel opening or resizing, reflows the
    rows; a `following` view then keeps to the end also with auto-scroll off. The
    typewriter's drain is a pause (`pauseFollowing`), and the view catches up
    when it ends. Do not write `scrollTop` while the user scrolls: a following
    view catches up once the input settles. Keep native scroll anchoring on: a
    script write stops a trackpad fling.
    **Opening a step reveals it.** When the user opens a run card or a step,
    `lib/chatScroll/hooks.ts:useRevealOnOpen` waits `FOLD_OPEN_MS` for the fold
    to reach its full height, then the action from the container's `prepareReveal` scrolls by the smaller of
    the part of the row hidden below and the room above it. The footer's height (a
    spacer the height of the composer laid over the view) counts as hidden.
    It does nothing while the view follows a streaming reply (`isStreaming`) with
    auto-scroll on, or when the user closes the row again during the wait, and
    jumps instead of gliding under reduced motion. Otherwise it makes the view a
    reading one, so the click's catch-up does not jump a following idle view to
    the end.
    **Turn anchoring is layout.** `sections/chat/ChatUI.tsx` groups each turn (a
    user message and its replies) in a `data-chat-turn` element. The latest turn
    has `min-height: calc(100cqh - 3rem - var(--app-composer-height))` (the
    scroll element is a size container): at the end of every chat, in every tab and after a reload, the
    latest user message sits 1rem below the top, with space below it, while the
    turn fits in that height. A taller turn ends at the bottom, and its user
    message is above the viewport. Nothing
    measures it. A send glides to the end through
    `lib/chatScroll/hooks.ts:useScrollToNewTurn` (only while the chat is
    `loading`, and not on a switch back to a running chat, so a resumed run
    never moves the view). The scroll-to-bottom button ignores the latest
    turn's unfilled space. Text that grows inside that space changes no scroll
    height, so a ResizeObserver watches the latest turn's rows.
    In a chat, `views/AppPage.tsx` lays the composer row over the scroll area,
    so the scrollbar spans the page. `@opal/hooks:usePublishedHeight`
    publishes the row's height as `--app-composer-height`, which keeps the
    chat's end clear of the composer: a footer spacer (not content, so "at the
    bottom" ignores it), the latest turn's minimum height, and
    `scroll-padding-bottom` for focus and `scrollIntoView`.
    The button names why to return (`lib/chat/hooks.ts:useJumpToLatestReason`):
    a waiting approval, a waiting question, or new output from a run that went
    on after the button appeared and has ended. Output that only loads, such
    as an opened chat's history, does not count. Otherwise it is a bare
    chevron.
    Each chat's position (end, or a row and offset) and its row heights live
    in `lib/chatScroll/scrollMemory.ts`; the opening layout effect restores
    them from loaded rows only, so a switch never waits on the network. Rows
    use `lib/chat/rowIds.ts:messageRowId`.
    Craft's transcript (`app/craft/components/ChatPanel.tsx`) uses the same
    `ChatScrollContainer`, with its composer in the `footer` slot. Its rows are
    not turn groups, so Craft has no space below its latest turn.

---

## Decisions

- **Packets pass through a FIFO and flush once per animation frame.** The
  network delivers many small chunks. A React update per chunk would stall the
  page, so the drain loop in `onSubmit` batches them.
- **Each session has its own store entry.** A stream keeps running while the
  user reads another chat, and its result is there when they return.
- **The page-level `Dropzone` sets `noClick` and `noPaste`.** The input bar
  handles click and paste uploads. Without `noPaste`, one paste attaches the
  file twice.

---

## Known issues

- **A multi-model send that hits the usage limit shows no banner.** In a
  multi-model turn `onSubmit` drops a `StreamingError` without
  `details.model_index`, and the 429 packet has none. The panels also get no
  stop packet.
- **A fast send after a branch switch can race.** `patchMessageToBeLatest` is
  not awaited. A send that reaches the server first can fail with "not on the
  latest mainline". This is inferred from the code, not seen in a test.
- **The server names a new chat.** It names it during the first turn and sends
  a `chat_session_name` line, because `sendMessage` sets
  `accepts_chat_session_name`. `handleNewSessionNaming` runs only when the
  stream ends without that line. It and the session controller's on-load naming
  call `PUT /chat/rename-chat-session`, which returns a saved name or waits for
  one in progress (one naming lock per chat, `backend/onyx/chat/session_naming.py`).

---

## Dependencies

- [[core-chat-loop]]: the send, stop, resume and status endpoints.
- [[streaming-protocol]]: the packets this component parses and renders.
- [[chat-persistence]]: session reads, replay packets, branch and pick
  endpoints, feedback, sharing and incognito teardown.
- [[citations]]: marker resolution inside the answer.
- [[agents-personas]]: the active agent from `agentId`.
- [[projects]]: `ProjectsProvider` and project context.
- [[llm-providers]]: `useLlmManager` and model capabilities.
- [[file-store-and-user-files]]: `beginUpload` and attached files.
- [[voice]]: `VoiceModeProvider` wraps the layout.
- [[plugins]]: the Action-preference rule and the member plugins sent with a turn.
- [[rate-and-usage-limits]]: the 429 usage-limit response shape.

---

## Recipes

- `packet-type-renderer` **A packet type.** Copy how `FILE_READER_START` is
  handled; list the web sets with the `git grep` in
  [[#packet-type-web-sets]]. Add a renderer to `findRenderer`. Cover it with a
  mocked stream ([[#mock-stream-test]]).
- `message-action` **A message action.** Copy regenerate, which routes through `onSubmit`
  with `messageIdToResend`, if the action sends a turn. Otherwise copy
  `patchMessageToBeLatest`; list the client calls in
  `app/app/services/lib.tsx`. Update the tree in the store, and check that a
  reload shows the same result.
- `query-parameter` **A query parameter.** Copy `PROJECT_ID`; list the set in
  `app/app/services/searchParams.ts:SEARCH_PARAM_NAMES`. Add it to
  `PARAMS_TO_SKIP` if it must not survive navigation
  ([[#chat-url-drops-ids]]).
- `mock-stream-test` **Test a renderer with no LLM.** Copy a spec in `web/tests/e2e/chat/` that
  calls `mockChatEndpoint`. `web/tests/e2e/utils/chatMock.ts` builds a stream
  by hand (`buildMockStream`, `buildMockSearchStream`), and
  `web/tests/e2e/utils/chatStream.ts` parses a captured stream for
  assertions.
- `remote-backend` **Run the web app against another backend.** In development, set
  `INTERNAL_URL` to the backend origin. For a backend that needs a session,
  copy the auth cookie value from that site into `DEBUG_AUTH_COOKIE`. The
  proxy adds it to each request ([[#dev-api-proxy-only]]).

---

## Verification

- Playwright: the specs in `web/tests/e2e/chat/`, with the stream mocks in
  `web/tests/e2e/utils/`.
- Jest: the `*.test.ts` and `*.test.tsx` files beside the code in
  `web/src/app/app/`.
- By hand: select an Action preference, edit, switch back, stop mid-answer, and reload.
  Citations resolve, the branch holds, and the partial answer stays. Queue a
  message with Ctrl/Cmd+Enter during an answer: the server starts it after completion.
  Enter adds text at the next model step by default. Choose Send now on a
  queued message to interrupt. Reload and verify pending and accepted text.

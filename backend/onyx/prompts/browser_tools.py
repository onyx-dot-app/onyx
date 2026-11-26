# Descriptions of the browser tools that the model reads
# (tools/tool_implementations/sandbox/browser_tools.py).

BROWSER_STATUS_DESCRIPTION = (
    "Report this chat's browser tabs: ID, URL, title, loading, who controls "
    "each tab (agent, human or none) and a pending dialog, plus your current "
    "tab. Works on a tab that the user controls."
)
BROWSER_OPEN_DESCRIPTION = """Open a page in this chat's browser and make the tab your current tab. Reuses your current tab unless `new_tab` is true or there is none. Returns the tab.

Usage:
- The browser is a real Chrome that keeps the user's sign-ins. Use it and the other browser tools to browse the web.
- The user can watch the tabs live in the chat's browser panel and take control of a tab.
- An action on a tab that the user controls fails. Then open a new tab with `new_tab` true, or ask the user to release control.
- When a page needs a sign-in, ask the user to sign in for you."""
BROWSER_NAVIGATE_DESCRIPTION = (
    "Navigate a tab: pass `url` for a page, or `history` to go back, forward "
    "or reload. Exactly one of them."
)
BROWSER_SNAPSHOT_DESCRIPTION = (
    "Use it only when the request asks for browser work. Returns the page "
    "title, URL and an accessibility tree of the page with element refs "
    "(such as e3_12) for browser_act and browser_wait_for. Refs die on "
    "navigation and on the next snapshot of the tab. Text caps near 20,000 "
    "characters; browser_evaluate reads more. Works on a tab that the user "
    "controls. `screenshot_path` also writes a PNG screenshot there, in the "
    "working directory; publish it with publish_files to show it."
)
BROWSER_ACT_DESCRIPTION = (
    "Act on a tab. Target an element with `ref` from browser_snapshot, a CSS "
    "`selector`, or `x` and `y` together (CSS pixels). `timeout_ms` defaults "
    "to 15000. click: `button`, `click_count` 1 to 3. type: literal `text`; "
    "`clear` replaces the value. hover: shows menus or tooltips. select: "
    "`values` in one native <select>, by value or label; for a custom "
    "dropdown, click it open, then click the option. drag: `ref` onto "
    "`target_ref`. upload: `paths` in the working directory answer the open "
    "file picker, or set the <input type=file> that `ref` names; [] cancels "
    "the picker. press: one `key`, such as 'Enter', with `modifiers`, to the "
    "focused element; click a field first to focus it. scroll: the page, or "
    "the container that `ref` names; positive `delta_y` scrolls down, "
    "positive `delta_x` right. Fails at once on a tab that the user controls."
)
BROWSER_WAIT_FOR_DESCRIPTION = (
    "Wait until all the given conditions match in a tab: the element `ref` "
    "or `selector` is visible, the page shows `text`, the URL contains "
    "`url_includes`. Works on a tab that the user controls."
)
BROWSER_EVALUATE_DESCRIPTION = (
    "Run JavaScript in the page and return its JSON value, up to 64 KB. It "
    "can change page state. To read a tab that the user controls, use "
    "browser_snapshot."
)
BROWSER_DIALOG_DESCRIPTION = (
    "Accept or dismiss the dialog (alert, confirm, prompt) that "
    "browser_status reports. Pass `prompt_text` to answer a prompt."
)

TAB_ARGUMENT = "Tab ID from browser_status or browser_open. Default: your current tab."
URL_ARGUMENT = "Absolute http(s) URL, or a bare host (https)."
TIMEOUT_ARGUMENT = "Milliseconds, 1 to 60000. Default 15000."

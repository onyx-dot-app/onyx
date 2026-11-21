package tui

const helpText = `Onyx CLI Commands

  /help              Show this help message
  /clear             Clear chat and start a new session
  /agent             List and switch agents (by ID or name)
  /model             List and switch models
  /attach <path>     Attach a file to next message
  /sessions          Browse and resume previous sessions
  /configure         Re-run connection setup
  /connectors        Open connectors page in browser
  /settings          Open Onyx settings in browser
  /experiments       List experimental features and their status
  /quit              Exit Onyx CLI

Keyboard Shortcuts

  Enter              Send message
  Escape, Ctrl+C     Cancel current generation
  y / a / n          Approve once / approve for this session / reject a tool call
  d                  Show all arguments of a tool call that waits for approval
  Up/Down, Enter     Select and confirm a tool approval action or an answer
                     to the agent's question
  Ctrl+O             Toggle source citations
  Ctrl+D             Quit (press twice)
  Scroll Up/Down     Mouse wheel or Shift+Up/Down
  Page Up/Down       Scroll half page
`

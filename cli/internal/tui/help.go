package tui

const helpText = `Onyx CLI Commands

  /help              Show this help message
  /clear             Clear chat and start a new session
  /agent             List and switch agents
  /attach <path>     Attach a file to next message
  /sessions          Browse and resume previous sessions
  /configure         Re-run connection setup
  /connectors        Open connectors page in browser
  /settings          Open Onyx settings in browser
  /skills            List local skills and reload them from disk
  /experiments       List experimental features and their status
  /quit              Exit Onyx CLI

Skills

  Put a SKILL.md file in .agents/skills/<name>/ (project) or
  ~/.agents/skills/<name>/ (global) to get a /<name> command. Running it
  sends the file content as your next message. Text after the command name
  replaces $ARGUMENTS, or is appended when the skill has no placeholder.

Keyboard Shortcuts

  Enter              Send message
  Escape             Cancel current generation
  Ctrl+O             Toggle source citations
  Ctrl+D             Quit (press twice)
  Scroll Up/Down     Mouse wheel or Shift+Up/Down
  Page Up/Down       Scroll half page
`

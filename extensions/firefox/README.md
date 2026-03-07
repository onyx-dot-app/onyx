# Onyx Firefox Extension

The Onyx Firefox extension lets you research, create, and automate with LLMs powered by your team's unique knowledge. Just hit Ctrl + O to instantly access Onyx in your browser:

💡 Know what your company knows, instantly with the Onyx sidebar
💬 Chat: Onyx provides a natural language chat interface as the main way of interacting with the features.
🌎 Internal Search: Ask questions and get answers from all your team's knowledge, powered by Onyx's 50+ connectors to all the tools your team uses
🚀 With a simple Ctrl + O - instantly summarize information from any work application

⚡️ Get quick access to the work resources you need.
🆕 Onyx new tab page puts all of your company's knowledge at your fingertips
🤖 Access custom AI Agents for unique use cases, and give them access to tools to take action.

—

Onyx connects with dozens of popular workplace apps like Google Drive, Jira, Confluence, Slack, and more. Use this extension if you have an account created by your team admin.

## Features

- **Sidebar Panel**: Access Onyx chat directly from the browser sidebar
- **New Tab Override**: Replace your new tab page with Onyx for quick access
- **Omnibox Integration**: Type `onyx` in the address bar followed by a space to search directly
- **Text Selection**: Select text on any page and click the Onyx icon to query about it
- **Keyboard Shortcuts**: 
  - `Ctrl+O` (or `Cmd+Ctrl+O` on Mac): Toggle Onyx sidebar
  - `Ctrl+Shift+O` (or `Cmd+Shift+O` on Mac): Toggle new tab override

## Installation

### From Firefox Add-ons (Recommended)
*Coming soon - pending review*

### Manual Installation (Development)

1. Open Firefox and navigate to `about:debugging`
2. Click "This Firefox" in the left sidebar
3. Click "Load Temporary Add-on..."
4. Navigate to this directory and select the `manifest.json` file

### Development

1. Make changes to files in the `src` directory
2. If you have the extension loaded temporarily, click "Reload" in `about:debugging`
3. For persistent development, consider using `web-ext` tool:
   ```bash
   npm install -g web-ext
   web-ext run
   ```

## Project Structure

```
firefox/
├── manifest.json          # Extension manifest (Firefox MV3)
├── background.js          # Background service worker
├── public/               # Icons and static assets
│   ├── icon16.png
│   ├── icon32.png
│   ├── icon48.png
│   ├── icon128.png
│   └── logo.png
└── src/
    ├── pages/            # Extension pages
    │   ├── sidebar.html/js    # Sidebar panel
    │   ├── popup.html/js      # Toolbar popup
    │   ├── options.html/js    # Settings page
    │   ├── welcome.html/js    # First-run onboarding
    │   └── onyx_home.html/js  # New tab page
    ├── styles/           # CSS stylesheets
    │   ├── shared.css
    │   └── selection-icon.css
    └── utils/            # Shared utilities
        ├── constants.js
        ├── storage.js
        ├── error-modal.js
        └── selection-icon.js
```

## Configuration

After installation, the extension will guide you through setup:

1. **Root Domain**: Enter your Onyx instance URL (e.g., `https://cloud.onyx.app`)
2. **New Tab Page**: Choose whether to use Onyx as your new tab page

You can change these settings anytime by clicking the extension icon and selecting "Extension Settings".

## Contributing

Submit issues or pull requests for improvements

## License

See the LICENSE file for details.

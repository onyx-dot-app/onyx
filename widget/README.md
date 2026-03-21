# Onyx Chat Widget

An embeddable, lightweight chat widget that brings AI-powered conversations to any website. Built with [Lit](https://lit.dev/) web components for maximum compatibility and minimal bundle size.

## Security Note

⚠️ **Always use a limited-scope API key for the widget.** The API key is visible in client-side code, so it should have restricted permissions and rate limits. Never use admin or full-access keys.

## Features

- 🚀 **Lightweight** - ~100-150kb gzipped bundle
- 🎨 **Fully Customizable** - Colors, branding, and styling
- 📱 **Responsive** - Desktop popup, mobile fullscreen
- 🔒 **Shadow DOM Isolation** - No style conflicts with your site
- 💬 **Real-time Streaming** - Server-sent events (SSE) for fast responses
- 🌐 **Two Deployment Modes** - Cloud CDN or self-hosted
- ♿ **Markdown Support** - Rich text formatting in responses
- 💾 **Session Persistence** - Conversations survive page reloads
- 🎯 **Two Display Modes** - Floating launcher or inline embed

## Quick Start

### Cloud Deployment (Recommended)

Add these two lines to your website:

```html
<!-- Load the widget -->
<script type="module" src="https://cdn.onyx.app/widget/1.0/dist/onyx-widget.js"></script>

<!-- Configure and display -->
<onyx-chat-widget
  backend-url="https://cloud.onyx.app/api"
  api-key="your_api_key_here"
  mode="launcher"
>
</onyx-chat-widget>
```

That's it! The widget will appear as a floating button in the bottom-right corner.

## How It Works

### Architecture Overview

```
┌─────────────────────────────────────────┐
│         Customer Website                │
│  ┌───────────────────────────────────┐  │
│  │  <onyx-chat-widget>               │  │
│  │  (Web Component)                  │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │    Shadow DOM               │  │  │
│  │  │  • Isolated styles          │  │  │
│  │  │  • UI components            │  │  │
│  │  │  • Message history          │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└──────────────┬──────────────────────────┘
               │ API Calls (SSE)
               ▼
┌──────────────────────────────────────────┐
│         Onyx Backend                     │
│  • POST /api/chat/create-chat-session    │
│  • POST /api/chat/send-chat-message      │
│  • Streams responses via SSE             │
└──────────────────────────────────────────┘
```

### Technology Stack

- **Frontend Framework**: [Lit](https://lit.dev/) - Lightweight web components
- **Markdown Rendering**: [marked.js](https://marked.js.org/)
- **Build Tool**: [Vite](https://vitejs.dev/)
- **Styling**: CSS-in-JS with Shadow DOM isolation
- **API Communication**: Fetch API with SSE (Server-Sent Events)

### Component Structure

```
<onyx-chat-widget>
  └─ Shadow DOM
      ├─ Launcher Button (mode="launcher" only)
      └─ Chat Container
          ├─ Header
          │   ├─ Logo/Avatar
          │   ├─ Agent Name
          │   └─ Actions (Reset, Close)
          ├─ Disclaimer
          ├─ Messages
          │   ├─ User Messages
          │   ├─ Assistant Messages (with markdown)
          │   └─ Typing Indicator
          └─ Input Area
              ├─ Text Input
              ├─ Send Button
              └─ "Powered by Onyx" Footer
```

## Configuration Options

### Required Attributes

| Attribute     | Type   | Description                                                          |
| ------------- | ------ | -------------------------------------------------------------------- |
| `backend-url` | string | Your Onyx backend API URL (or set `VITE_WIDGET_BACKEND_URL` in .env) |
| `api-key`     | string | API key for authentication (or set `VITE_WIDGET_API_KEY` in .env)    |

**Note**: For cloud deployment, these must be provided as HTML attributes. For self-hosted deployment, they can be set in `.env` file during build and will be baked into the bundle.

### Optional Attributes

| Attribute          | Type   | Default       | Description                              |
| ------------------ | ------ | ------------- | ---------------------------------------- |
| `agent-id`         | number | `undefined`   | Specific agent/persona to use            |
| `agent-name`       | string | `"Assistant"` | Display name in header                   |
| `logo`             | string | Onyx logo     | URL to custom logo image                 |
| `primary-color`    | string  | `#1c1c1c`     | Primary brand color (buttons, accents)   |
| `background-color` | string  | `#e9e9e9`     | Widget background color                  |
| `text-color`       | string  | `#000000bf`   | Text color (75% opacity black)           |
| `mode`             | string  | `"launcher"`  | Display mode: `"launcher"` or `"inline"` |
| `include-citations`| boolean | `false`       | Include citation markers in responses    |

**Note**: These attributes must be provided as HTML attributes. Only `backend-url` and `api-key` can optionally be set via environment variables for self-hosted builds.

### Configuration Examples

**Basic Setup:**

```html
<onyx-chat-widget backend-url="https://cloud.onyx.app/api" api-key="on_abc123">
</onyx-chat-widget>
```

**Full Customization:**

```html
<onyx-chat-widget
  backend-url="https://cloud.onyx.app/api"
  api-key="on_abc123"
  agent-id="42"
  agent-name="Support Bot"
  logo="https://yoursite.com/logo.png"
  primary-color="#FF6B35"
  background-color="#FFFFFF"
  text-color="#1A1A1A"
  mode="launcher"
>
</onyx-chat-widget>
```

**Inline Mode (Embedded):**

```html
<div style="width: 400px; height: 600px;">
  <onyx-chat-widget
    backend-url="https://cloud.onyx.app/api"
    api-key="on_abc123"
    mode="inline"
  >
  </onyx-chat-widget>
</div>
```

## Display Modes

### Launcher Mode (Default)

A floating button appears in the bottom-right corner. Clicking it opens a chat popup.

- **Desktop**: 400x600px popup above the button
- **Mobile (<768px)**: Full-screen overlay

```html
<onyx-chat-widget mode="launcher"></onyx-chat-widget>
```

### Inline Mode

The widget is embedded directly in your page layout. Perfect for dedicated support pages.

```html
<div class="chat-container">
  <onyx-chat-widget mode="inline"></onyx-chat-widget>
</div>
```

**CSS Tip**: The widget will fill its container's dimensions in inline mode.

## Development

### Prerequisites

- Node.js 18+ and npm
- Access to Onyx backend API

### Setup

```bash
# Navigate to widget directory
cd widget/

# Install dependencies
npm install

# Copy example env file (for self-hosted builds)
cp .env.example .env
```

### Development Server

```bash
npm run dev
```

Opens at `http://localhost:5173` with hot module replacement.

### Build Commands

```bash
# Cloud deployment (no config baked in)
npm run build:cloud

# Self-hosted deployment (config from .env)
npm run build:self-hosted

# Standard build (same as cloud)
npm run build
```

### Project Structure

```
widget/
├── src/
│   ├── index.ts                 # Entry point
│   ├── widget.ts                # Main component
│   ├── config/
│   │   ├── config.ts            # Configuration resolver
│   │   └── build-config.ts      # Build-time config injection
│   ├── services/
│   │   ├── api-service.ts       # API client (SSE streaming)
│   │   └── stream-parser.ts     # SSE packet processor
│   ├── types/
│   │   ├── api-types.ts         # Backend packet types
│   │   └── widget-types.ts      # Widget configuration types
│   ├── styles/
│   │   ├── theme.ts             # Design tokens
│   │   ├── colors.ts            # Color system
│   │   └── widget-styles.ts     # Component styles
│   ├── utils/
│   │   └── storage.ts           # Session persistence
│   └── assets/
│       └── logo.ts              # Default Onyx logo (base64)
├── dist/                        # Build output
├── index.html
├── package.json
├── vite.config.ts
└── tsconfig.json
```

### Key Files

- **[src/widget.ts](src/widget.ts)** - Main Lit component with all UI logic
- **[src/services/api-service.ts](src/services/api-service.ts)** - Handles API calls and SSE streaming
- **[src/styles/widget-styles.ts](src/styles/widget-styles.ts)** - All CSS styles
- **[vite.config.ts](vite.config.ts)** - Build configuration (cloud vs self-hosted)

## API Integration

### Backend Endpoints Used

The widget communicates with these Onyx backend endpoints:

#### 1. Create Chat Session

```
POST /chat/create-chat-session
Content-Type: application/json
Authorization: Bearer YOUR_API_KEY

{
  "persona_id": 42  // Optional agent ID
}

Response:
{
  "chat_session_id": "uuid-here"
}
```

#### 2. Send Message (SSE Streaming)

```
POST /chat/send-chat-message
Content-Type: application/json
Authorization: Bearer YOUR_API_KEY

{
  "message": "User's question",
  "chat_session_id": "uuid-here",
  "parent_message_id": 123,  // null for first message
  "origin": "widget",
  "include_citations": false
}

Response: Server-Sent Events stream
{"type": "message_start"}
{"type": "message_delta", "content": "Hello"}
{"type": "message_delta", "content": " world!"}
{"type": "stop"}
```

## Deployment

### Self-Hosted Deployment

1. **Create `.env` file:**

   ```bash
   VITE_WIDGET_BACKEND_URL=https://your-backend.com
   VITE_WIDGET_API_KEY=your_api_key
   ```

2. **Build with config baked in:**

   ```bash
   npm run build:self-hosted
   ```

3. **Deploy `dist/onyx-widget.js` to your server**

4. **Customer embed:**
   ```html
   <script type="module" src="https://your-cdn.com/onyx-widget.js"></script>
   <onyx-chat-widget
     agent-id="1"
     agent-name="Support"
     logo="https://path-to-your-logo.com/"
   >
   </onyx-chat-widget>
   ```

## Customization

### Styling

The widget uses CSS custom properties (CSS variables) for theming. All styles are scoped within Shadow DOM to prevent conflicts.

**Default Colors (aligned with web/src/app/css/colors.css):**

```css
--theme-primary-05: #1c1c1c; /* Buttons, accents (activa-ink-95) */
--theme-primary-06: #000000; /* Hover state (activa-ink-100) */
--background-neutral-00: #ffffff; /* Widget background (grey-00) */
--background-neutral-03: #e6e6e6; /* Background hover (grey-10) */
--text-04: #000000bf; /* Text (alpha-grey-100-75) */
--text-light-05: #ffffff; /* White text on dark (grey-00) */
--border-01: #00000033; /* Borders (alpha-grey-100-20) */
```

**Override via attributes:**

```html
<onyx-chat-widget
  primary-color="#FF6B35"
  background-color="#FFFFFF"
  text-color="#1A1A1A"
>
</onyx-chat-widget>
```

## Browser Support

- ✅ Chrome/Edge 90+ (Chromium)
- ✅ Firefox 90+
- ✅ Safari 15+
- ✅ Mobile Safari (iOS 15+)
- ✅ Mobile Chrome (Android)

**Requirements:**

- ES Modules support
- Custom Elements v1
- Shadow DOM v1
- Fetch API with SSE

## Performance

- **Bundle Size**: ~100-150kb gzipped
- **Initial Load**: Shadow DOM renders immediately
- **Message Latency**: Real-time SSE streaming (<100ms first token)
- **Session Persistence**: sessionStorage (auto-save on each message)

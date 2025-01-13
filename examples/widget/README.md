# Onyx Chat Bot Widget

Note: The widget requires a Onyx API key, which is a paid (cloud/enterprise) feature.

This is a code example for how you can use Onyx's APIs to build a chat bot widget for a website! The main code to look at can be found in `src/app/widget/Widget.tsx`.

## Getting Started

To get the widget working on your webpage, follow these steps:

### 1. Install Dependencies

Ensure you have the necessary dependencies installed. From the `examples/widget/README.md` file:

```bash
npm i
```

### 2. Set Environment Variables

Make sure to set the environment variables `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_API_KEY` in a `.env` file at the root of your project:

```bash
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_API_KEY=
```

### 3. Run the Development Server

Start the development server to see the widget in action.

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### 4. Integrate the Widget

To integrate the widget into your webpage, you can use the `ChatWidget` component. Here’s an example of how to include it in a page component:

```jsx
import ChatWidget from "path/to/ChatWidget";
function MyPage() {
  return (
    <div>
      <h1>My Webpage</h1>
      <ChatWidget />
    </div>
  );
}
export default MyPage;
```

### 5. Deploy

Once you are satisfied with the widget, you can build and start the application for production:

```bash
npm run build
npm run start
```

### Custom Styling and Configuration

If you need to customize the widget, you can modify the `ChatWidget` component in the `examples/widget/src/app/widget/Widget.tsx` file.

By following these steps, you should be able to get the chat widget working on your webpage.

If you want to get fancier, then take a peek at the Chat implementation within Onyx itself [here](https://github.com/onyx-dot-app/onyx/blob/main/web/src/app/chat/ChatPage.tsx#L82).

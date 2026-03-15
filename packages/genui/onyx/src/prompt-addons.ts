/**
 * Onyx-specific prompt rules and examples that augment the
 * auto-generated component documentation.
 */
export const onyxPromptAddons = {
  rules: [
    "Use Stack for vertical layouts and Row for horizontal layouts",
    "For tables, pass column headers as a string array and rows as arrays of values",
    "Tags are great for showing status, categories, or labels inline",
    "Use Alert for important status messages — choose the right level (info, success, warning, error)",
    "Buttons need an actionId to trigger events — the UI framework handles the callback",
    "Keep layouts simple — prefer flat structures over deeply nested ones",
    "For search results or document lists, use Table with relevant columns",
    "Use Card to visually group related content",
  ],

  examples: [
    {
      description: "Search results with table",
      code: `title = Text("Search Results", headingH2: true)
row1 = ["Onyx Docs", Tag("PDF", color: "blue"), "2024-01-15"]
row2 = ["API Guide", Tag("MD", color: "green"), "2024-02-01"]
results = Table(["Name", "Type", "Date"], [row1, row2])
action = Button("View All", main: true, primary: true, actionId: "viewAll")
root = Stack([title, results, action], gap: "md")`,
    },
    {
      description: "Status card with actions",
      code: `status = Alert("Pipeline completed successfully", level: "success")
stats = Row([
  Text("Processed: 1,234 docs"),
  Text("Duration: 2m 34s", muted: true)
], gap: "lg")
actions = Row([
  Button("View Results", main: true, primary: true, actionId: "viewResults"),
  Button("Run Again", action: true, secondary: true, actionId: "rerun")
], gap: "sm")
root = Stack([status, stats, actions], gap: "md")`,
    },
    {
      description: "Simple info display",
      code: `root = Card(title: "Document Summary")`,
    },
  ],
};

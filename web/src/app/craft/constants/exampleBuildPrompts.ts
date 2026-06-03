/**
 * Example prompts for the Build Mode welcome screen.
 */

export interface BuildPrompt {
  id: string;
  /** Short summary shown on the button */
  summary: string;
  /** Full prompt text inserted into the input bar */
  fullText: string;
  /** Optional image URL/path for visual display */
  image?: string;
}

/**
 * Example prompts shown on the welcome screen.
 */
export const exampleBuildPrompts: BuildPrompt[] = [
  {
    id: "default-1",
    summary: "Analyze team productivity by month across my company",
    fullText:
      "Create a dashboard with the number of closed tickets per month. Split by priority and compare teams.",
    image: "/craft_suggested_image_1.png",
  },
  {
    id: "default-2",
    summary:
      "Visualize what my team did this month with interactive drill-downs",
    fullText:
      "What did my team work on this month? Create a dashboard that 1) shows the number of actions per activity, 2) shows the individual work items when I select something in the dashboard.",
    image: "/craft_suggested_image_2.png",
  },
  {
    id: "default-3",
    summary: "Connect my backlog to recent customer conversations",
    fullText:
      "For each of my open Linear tickets, find at least 2 customers that have discussed related issues. Present the results in a dashboard table.",
    image: "/craft_suggested_image_3.png",
  },
  {
    id: "default-4",
    summary:
      "Surface the top pain points from this week's customer success calls",
    fullText:
      "Based on the customer calls this week, what are the 5 most important challenges? Create a table in a dashboard that shows the challenge and the customers that complained about it.",
    image: "/craft_suggested_image_4.png",
  },
  {
    id: "default-5",
    summary:
      "Compare and contrast which messaging resonates the most with our prospects",
    fullText:
      "If you look at the customer calls over the last 30 days, which part of our messaging seems to resonate the best, and appears to drive the most customer value? Generate a slide that effectively tells the story.",
    image: "/craft_suggested_image_5.png",
  },
];

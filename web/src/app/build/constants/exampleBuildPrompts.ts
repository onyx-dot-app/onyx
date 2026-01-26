/**
 * Example prompts for the Build Mode welcome screen.
 * Organized by user persona to allow different prompts for different user types.
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

export type UserPersona = "default" | "engineering" | "sales" | "product";

/**
 * Example prompts organized by user persona.
 * Each persona has a set of prompts tailored to their typical use cases.
 */
export const exampleBuildPrompts: Record<UserPersona, BuildPrompt[]> = {
  default: [
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
  ],
  engineering: [
    {
      id: "eng-1",
      summary: "Enrich my open PRs with customer insights and feedback",
      fullText:
        "Look at my open PRs and find information from customer discussions regarding these PRs that could help to implement better. Also find for each PR the design doc I wrote and create a new one that is appropriately updated.",
      image: "/craft_suggested_image_1.png",
    },
    {
      id: "eng-2",
      summary: "Track engineering velocity from ticket to merged PR",
      fullText:
        "What is the average time it takes the engineers to merge PRs after my team created a Linear ticket? Create a dashboard that shows the average time by engineering team.",
      image: "/craft_suggested_image_2.png",
    },
    {
      id: "eng-3",
      summary: "Build a visual roadmap story from my quarterly contributions",
      fullText:
        "Create an image (slide) that groups my PRs by quarter, finds the common thread, and presents a coherent story. This will later go into a historical roadmap.",
      image: "/craft_suggested_image_3.png",
    },
    {
      id: "eng-4",
      summary:
        "Find churned customers who would have benefited from our releases",
      fullText:
        "Look at the PRs that my team merged this month. Then look at the customers we lost over the last 2 months and tell me which of the customers would have likely benefitted from the merged PRs. Rank the customers by importance. Present in a dashboard.",
      image: "/craft_suggested_image_4.png",
    },
    {
      id: "eng-5",
      summary: "Build a Linear dashboard to track my team's progress",
      fullText: "Create a Linear dashboard for my team.",
      image: "/craft_suggested_image_5.png",
    },
  ],
  sales: [
    {
      id: "sales-1",
      summary: "Identify sales blockers and quantify their revenue impact",
      fullText:
        "Look at the customer calls that my team had last month and identify the 3 most important sales blockers. Those could be product-related, messaging-related, or persona-chemistry. Create a dashboard showing how much revenue seems to be associated with each blocker.",
      image: "/craft_suggested_image_1.png",
    },
    {
      id: "sales-2",
      summary: "Prepare winning talking points for my upcoming meeting",
      fullText:
        "I have a meeting with a prospect next week. Please go through the objections they raised and suggest good talking points based on other customer situations, upcoming product changes, etc.",
      image: "/craft_suggested_image_2.png",
    },
    {
      id: "sales-3",
      summary: "Learn how my teammates overcame similar deal objections",
      fullText:
        "I don't want to give up on this opportunity. Find customer discussions from other members of my team where similar issues came up and were overcome. Provide some recommendations.",
      image: "/craft_suggested_image_3.png",
    },
    {
      id: "sales-4",
      summary: "Discover which pitch messaging resonates most with customers",
      fullText:
        "If you look at the customer calls over the last 30 days, which part of our messaging seems to resonate the best, and appears to drive the most customer value? Generate a slide that effectively tells the story.",
      image: "/craft_suggested_image_4.png",
    },
    {
      id: "sales-5",
      summary: "Surface the top product challenges from customer calls",
      fullText:
        "Based on the customer calls this week, what are the 5 most important challenges with the product? Create a table in a dashboard that shows the challenge and the customers that complained about it.",
      image: "/craft_suggested_image_5.png",
    },
  ],
  product: [
    {
      id: "product-1",
      summary: "Summarize what I did this month for my manager",
      fullText:
        "I need to explain to my manager what I did last month, and how it matters for customer impact.",
      image: "/craft_suggested_image_1.png",
    },
    {
      id: "product-2",
      summary: "Connect my backlog to recent customer conversations",
      fullText:
        "For each of my open Linear tickets, find at least 2 customers that have discussed related issues. Present the results in a dashboard table.",
      image: "/craft_suggested_image_2.png",
    },
    {
      id: "product-3",
      summary:
        "Visualize what my team did this month with interactive drill-downs",
      fullText:
        "What did my team work on this month? Create a dashboard that 1) shows the number of actions per activity, 2) shows the individual work items when I select something in the dashboard.",
      image: "/craft_suggested_image_4.png",
    },
    {
      id: "product-4",
      summary:
        "Find churned customers who would have benefited from the releases this month",
      fullText:
        "Look at the PRs that my team merged this month. Then look at the customers we lost over the last 2 months and tell me which of the customers would have likely benefitted from the merged PRs. Rank the customers by importance. Present in a dashboard.",
      image: "/craft_suggested_image_3.png",
    },
    {
      id: "product-5",
      summary: "Analyze team productivity by month across my company",
      fullText:
        "Create a dashboard with the number of closed tickets per month. Split by priority and compare teams.",
      image: "/craft_suggested_image_5.png",
    },
  ],
};

/**
 * Get prompts for a specific user persona.
 * Falls back to default prompts if persona is not found.
 */
export function getPromptsForPersona(persona: UserPersona): BuildPrompt[] {
  return exampleBuildPrompts[persona] ?? exampleBuildPrompts.default;
}

/**
 * Maps a workArea value from the build_user_persona cookie to a UserPersona.
 * Work areas that don't have dedicated prompts (executive, marketing, other) fall back to default.
 */
export function workAreaToPersona(workArea: string | undefined): UserPersona {
  switch (workArea) {
    case "engineering":
      return "engineering";
    case "sales":
      return "sales";
    case "product":
      return "product";
    default:
      return "default";
  }
}

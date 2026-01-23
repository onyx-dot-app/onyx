# AGENTS.md

This file provides guidance for AI agents when working in this sandbox.

## Structure

The `files` directory contains all of the knowledge from Chris' company, Onyx. This knowledge comes from Google Drive, Linear, Slack, Github, and Fireflies.

Each source has it's own directory - `Google_Drive`, `Linear`, `Slack`, `Github`, and `Fireflies`. Within each directory, the structure of the source is built out as a folder structure:

- Google Drive is copied over directly as is. End files are stored as `FILE_NAME.json`.
- Linear has each project as a folder, and then within each project, each individual ticket is stored as a file: `[TICKET_ID]_TICKET_NAME.json`.
- Slack has each channel as a folder titled `[CHANNEL_NAME]` in the root directory. Within each channel, each thread is represented as a single file called `[INITIAL_AUTHOR]_in_[CHANNEL]__[FIRST_MESSAGE].json`.
- Github has each organization as a folder titled `[ORG_NAME]`. Within each organization, there is 
a folder for each repository tilted `[REPO_NAME]`. Within each repository there are up to two folders: `pull_requests` and `issues`. Each pull request / issue is then represented as a single file
within the appropriate folder. Pull requests are structured as `[PR_ID]__[PR_NAME].json` and issues 
are structured as `[ISSUE_ID]__[ISSUE_NAME].json`.
- Fireflies has all calls in the root, each as a single file titled `CALL_TITLE.json`.
- HubSpot has four folders in the root: `Tickets`, `Companies`, `Deals`, and `Contacts`. Each object is stored as a file named after its title/name (e.g., `[TICKET_SUBJECT].json`, `[COMPANY_NAME].json`, `[DEAL_NAME].json`, `[CONTACT_NAME].json`).

Across all names, spaces are replaced by `_`.

Each JSON is structured like:

```
{
  "id": "afbec183-b0c5-46bf-b768-1ce88d003729",
  "semantic_identifier": "[CS-17] [Betclic] Update system prompt doesn't work",
  "title": "[Betclic] Update system prompt doesn't work",
  "source": "linear",
  "doc_updated_at": "2025-11-10T16:31:07.735000+00:00",
  "metadata": {
    "team": "Customer Success",
    "creator": "{'name': 'Chris Weaver', 'email': 'chris@danswer.ai'}",
    "state": "Backlog",
    "priority": "3",
    "created_at": "2025-11-10T16:30:10.718Z"
  },
  "doc_metadata": {
    "hierarchy": {
      "source_path": [
        "Customer Success"
      ],
      "team_name": "Customer Success",
      "identifier": "CS-17"
    }
  },
  "sections": [
    {
      "text": "Happens \\~15% of the time.",
      "link": "https://linear.app/onyx-app/issue/CS-17/betclic-update-system-prompt-doesnt-work"
    }
  ],
  "primary_owners": [],
  "secondary_owners": []
}
```

Do NOT write any files to these directories. Do NOT edit any files in these directories.

There is a special folder called `outputs`. Any and all python scripts, javascript apps, generated documents, slides, etc. should go here.
Feel free to write/edit anything you find in here.


## Outputs

**All outputs should be interactive web applications/dashboards** built with Next.js, React, and shadcn/ui.

### Web Applications / Dashboards

Web applications and dashboards should be written as a Next.js app. Within the `outputs` directory,
there is a folder called `web` that has the skeleton of a basic Next.js app in it.

The Next.js app is already running at a dynamically allocated port. Do not run `npm run dev` yourself.

**See `outputs/web/AGENTS.md` for detailed technical specifications, architecture patterns, component usage guidelines, and styling rules.**

### Other Output Formats (Coming Soon)

Additional output formats such as slides, markdown documents, and standalone graphs are coming soon. If the user requests these formats, let them know they're not yet available and suggest building an interactive web application instead, which can include:
- Data visualizations and charts using recharts
- Multi-page layouts with navigation
- Exportable content (print-to-PDF functionality)
- Interactive dashboards with real-time filtering and sorting

## Your Environment

You are in an ephemeral virtual machine with Node v22.21.1 and Python 3.11.13 available.

For JavaScript/TypeScript packages needed by your Next.js application, use `npm install <package>` from within the `outputs/web` directory. Common packages you might need are already available (recharts for charts, lucide-react for icons, etc.).  

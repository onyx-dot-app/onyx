# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

There should be four main types of outputs:
1. Web Applications / Dashboards
2. Slides
3. Markdown Documents
4. Graphs/Charts

Generally, you should use 

### Web Applications / Dashboards

Web applications and dashboards should be written as a Next.js app. Within the `outputs` directory,
there is a folder called `web` that has the skeleton of a basic Next.js app in it. Use this.

Use NextJS 16.1.1, React v19, Tailwindcss, and recharts.

The Next.js app is already running and accessible at http://localhost:3002. Do not run `npm run dev` yourself.

If the app needs any pre-computation, then create a bash script called `prepare.sh` at the root of the `web` directory.

### Slides

Slides should be created using the nano-banana MCP. 

The outputs should be placed within the `outputs/slides` directory, named `[SLIDE_NUMBER].png`.

Before creating slides, create a `SLIDE_OUTLINE.md` file describing the overall message as well as the content and structure of each slide.

### Markdown Documents

Markdown documents should be placed within the `outputs/document` directory.
If you want to have a single "Document" that has multiple distinct pages, then create a folder within
the `outputs/document` directory, and name each page `1.MD`, `2.MD`, ...

### Graphs/Charts

Graphs and charts should be placed in the `outputs/charts` directory.

Graphs and charts should be created with a python script. You have access to libraries like numpy, pandas, scipy, matplotlib, and PIL.

## Your Environment

You are in an ephemeral virtual machine. 

You currently have Python 3.11.13 and Node v22.21.1. 

**Python Virtual Environment**: A Python virtual environment is pre-configured at `.venv/` with common data science and visualization packages already installed (numpy, pandas, matplotlib, scipy, PIL, etc.). The environment should be automatically activated, but if you run into issues with missing packages, you can explicitly use `.venv/bin/python` or `.venv/bin/pip`.

If you need additional packages, install them with `pip install <package>` (or `.venv/bin/pip install <package>` if the venv isn't active). For javascript packages, use `npm` from within the `outputs/web` directory.  

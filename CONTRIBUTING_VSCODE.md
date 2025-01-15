# VSCode Debugging Setup

This guide explains how to set up and use VSCode's debugging capabilities with this project.

## Initial Setup

1. **Environment Setup**:
   - Copy `.vscode/.env.template` to `.vscode/.env`
   - Fill in the necessary environment variables in `.vscode/.env`
2. **launch.json**:
   - Copy `.vscode/launch.template.jsonc` to `.vscode/launch.json`

## Using the Debugger

Before starting, make sure the Docker Daemon is running.

1. Open the Debug view in VSCode (Cmd+Shift+D on macOS)
2. From the dropdown at the top, select "Clear and Restart External Volumes and Containers" and press the green play button
3. From the dropdown at the top, select "Run All Onyx Services" and press the green play button
4. Now, you can navigate to onyx in your browser (default is http://localhost:3000) and start using the app
5. You can set breakpoints by clicking to the left of line numbers to help debug while the app is running
6. Use the debug toolbar to step through code, inspect variables, etc.

## Features

- Hot reload is enabled for the web server and API servers
- Python debugging is configured with debugpy
- Environment variables are loaded from `.vscode/.env`
- Console output is organized in the integrated terminal with labeled tabs

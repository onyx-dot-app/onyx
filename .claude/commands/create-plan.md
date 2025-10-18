# Create Implementation Plan

Create a detailed implementation plan for the requested feature or change in the `plans` directory following the guidelines from CLAUDE.md.

## Steps:
1. Ask the user what feature or change they want to plan
2. If the user provides a Linear issue URL or ID, use the Linear MCP tools to fetch issue details for context
3. Research the relevant sections of the codebase using the Explore agent or appropriate tools
4. Identify the files, modules, and patterns involved
5. Create a plan file in the `plans` directory with a descriptive name (e.g., `add-authentication-to-api.md`)
6. Include the following sections in the plan:

### Required Sections:

**Issues to Address**
- What the change is meant to do
- What problem it solves or feature it adds

**Important Notes**
- Things discovered during research that are important to the implementation
- Key files, patterns, or constraints to be aware of

**Implementation Strategy**
- High-level approach to making the changes
- Which components will be modified or created
- How the pieces fit together

**Tests**
- What type of tests will be written (unit, external dependency unit, integration, or playwright)
- What behavior the tests will verify
- Don't overtest - usually a given change only needs one type of test

### Do NOT Include:
- Timeline estimates
- Rollback plans
- Actual code implementations (keep it high level)

## Important Notes:
- Do thorough research before writing the plan
- Explore relevant sections of the codebase
- Reference specific files and functions where appropriate
- Keep the plan high level - no code in the plan itself
- Follow Onyx conventions (see CLAUDE.md)
- If Linear MCP is available and a Linear issue is provided:
  - Use `mcp__linear-server__list_issues` to search for the issue
  - Include the Linear issue ID and title at the top of the plan
  - Incorporate issue description and acceptance criteria into the plan
  - Reference the Linear URL in the plan for traceability

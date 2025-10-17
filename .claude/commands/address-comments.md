# Address PR Comments

Fetch all review comments from the PR associated with the current branch and address them by making the necessary code changes.

## Steps:
1. Use `gh pr view --json number,reviews,reviewRequests,comments` to get the PR number and all comments for the current branch
2. Parse the review comments and identify what changes are needed
3. Read the relevant code files mentioned in the comments
4. Make the necessary code modifications to address each comment
5. Provide a summary of what was changed and ask if the user wants to commit the changes

## Important notes:
- Focus on review comments that request specific code changes
- Ignore comments that are just approvals or general discussion
- If a comment is unclear, make your best interpretation and note this in the summary
- Group related changes together when possible
- Always verify the changes make sense in context before proposing them

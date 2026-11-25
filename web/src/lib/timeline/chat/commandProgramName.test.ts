import { commandProgramName } from "@/lib/timeline/chat/commandProgramName";

test.each([
  ["npm test", "npm"],
  ["cd web && npm run build", "npm"],
  ["FOO=1 sudo python3 -m pytest", "python3"],
  ["/usr/bin/git status", "git"],
  ["bash -lc 'cd /app && pytest -q'", "pytest"],
  ["ls -la | grep x", "ls"],
  ["", null],
  ["$(echo hi)", null],
])("%s runs %s", (command, program) => {
  expect(commandProgramName(command)).toBe(program);
});

export const TEST_ADMIN_CREDENTIALS = {
  email: "admin_user@example.com",
  password: "TestPassword123!",
};

export const TEST_ADMIN2_CREDENTIALS = {
  email: "admin2_user@example.com",
  password: "TestPassword123!",
};

export function workerUserCredentials(workerIndex: number): {
  email: string;
  password: string;
} {
  return {
    email: `worker${workerIndex}@example.com`,
    password: "WorkerPassword123!",
  };
}

/**
 * Example TypeScript file for testing.
 */

interface User {
  id: number;
  name: string;
  email: string;
}

class UserManager {
  private users: User[] = [];

  addUser(user: User): void {
    this.users.push(user);
  }

  getUser(id: number): User | undefined {
    return this.users.find((u) => u.id === id);
  }

  getAllUsers(): User[] {
    return [...this.users];
  }
}

export { User, UserManager };

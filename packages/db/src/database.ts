/**
 * Thread-safe SQLite database wrapper for SmartBuilding Video.
 */
export class Database {
  private dbPath: string;

  constructor(dbPath: string) {
    this.dbPath = dbPath;
  }

  async initialize(): Promise<void> {
    // TODO: open DB connection, run migrations
  }

  async close(): Promise<void> {
    // TODO: close DB connection
  }
}

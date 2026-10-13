import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

const connectionString =
  process.env.DATABASE_URL ??
  process.env.POSTGRES_URL ??
  process.env.POSTGRES_PRISMA_URL ??
  (process.env.NODE_ENV === "production"
    ? undefined
    : "postgres://cfb:cfb@localhost:5433/highlights");

if (!connectionString) {
  throw new Error(
    "Missing database connection string. Set DATABASE_URL (or POSTGRES_URL) in environment variables.",
  );
}

// Reuse a single client across hot reloads in dev.
const globalForDb = globalThis as unknown as { client?: ReturnType<typeof postgres> };
const client =
  globalForDb.client ??
  postgres(connectionString, {
    prepare: false,
    connection: {
      search_path: "public",
    },
  });
if (process.env.NODE_ENV !== "production") globalForDb.client = client;

export const db = drizzle(client, { schema });

import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

const connectionString =
  process.env.DATABASE_URL ?? "postgres://cfb:cfb@localhost:5433/highlights";

// Reuse a single client across hot reloads in dev.
const globalForDb = globalThis as unknown as { client?: ReturnType<typeof postgres> };
const client = globalForDb.client ?? postgres(connectionString, { prepare: false });
if (process.env.NODE_ENV !== "production") globalForDb.client = client;

export const db = drizzle(client, { schema });

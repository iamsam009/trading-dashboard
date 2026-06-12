/**
 * MSW server instance for Node.js test environment.
 * Initialized in setup.ts; each test gets a fresh handler state.
 */

import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
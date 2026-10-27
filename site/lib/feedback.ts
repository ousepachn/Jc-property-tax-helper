// Visitor feedback: each submission is one small JSON file in Neon Object Storage (bucket `assets`,
// private), under feedback/YYYY-MM/. The site's database role stays read-only. Read them with
// `node --env-file=.env.local scripts/feedback.mjs` (see the script).
import { files } from "./storage";

export const TOPICS = {
  property_data: "Something's wrong with a property's data",
  not_found: "I couldn't find a property",
  idea: "An idea or suggestion",
  other: "Something else",
} as const;
export type Topic = keyof typeof TOPICS;

export const LIMITS = { message: 2000, email: 200, query: 120, page: 200 };

export interface Feedback {
  received_at: string;
  topic: Topic;
  message: string;
  email: string | null;
  pin: string | null;
  address: string | null; // looked up from the pin on the server, not taken from the visitor
  query: string | null; // what they typed in the search box
  page: string | null; // the page they came from
  user_agent: string | null;
}

export const feedbackConfigured = () => !!(process.env.AWS_ACCESS_KEY_ID && process.env.AWS_ENDPOINT_URL_S3);

export async function saveFeedback(f: Feedback) {
  const id = `${f.received_at.replace(/[:.]/g, "-")}-${crypto.randomUUID().slice(0, 8)}`;
  await files.upload(`feedback/${f.received_at.slice(0, 7)}/${id}.json`, JSON.stringify(f, null, 1), {
    contentType: "application/json",
  });
}

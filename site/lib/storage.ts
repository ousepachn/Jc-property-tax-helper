// Owners' documents (photos, appraisals, appeal evidence) in Neon Object Storage, bucket `assets`
// (private; declared in neon.ts). Credentials and endpoint come from the AWS_* variables Neon injects.
// Each owner's files sit under their own prefix; routes check the session before touching them.
import { Files } from "files-sdk";
import { neon } from "files-sdk/neon";

export const files = new Files({ adapter: neon({ bucket: "assets" }) });

export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024; // under Vercel's 4.5 MB request limit

export function ownerPrefix(userId: string) {
  return `owners/${userId}/`;
}

export function ownerKey(userId: string, filename: string) {
  const safe = filename.replace(/[^\w.-]+/g, "_").slice(-100) || "file";
  return `${ownerPrefix(userId)}${Date.now()}-${safe}`;
}

// the name the owner uploaded, without the timestamp
export function displayName(key: string) {
  return key.slice(key.lastIndexOf("/") + 1).replace(/^\d+-/, "");
}

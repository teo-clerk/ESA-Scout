/**
 * Strip credentials out of text that is about to be sent to a client.
 *
 * The sync endpoints forward upstream error bodies so an operator can see why
 * a dispatch failed. That detail is useful, but it must never carry a token
 * back out: these routes are reachable by anyone who can load the dashboard.
 */

const PLACEHOLDER = "[redacted]";

/** Shortest string still worth redacting; below this it is not a credential. */
const MIN_SECRET_LENGTH = 8;

export function redactSecrets(
  text: string,
  secrets: (string | undefined | null)[],
): string {
  let safe = text;
  for (const secret of secrets) {
    if (!secret || secret.length < MIN_SECRET_LENGTH) continue;
    safe = safe.split(secret).join(PLACEHOLDER);
  }
  return safe;
}

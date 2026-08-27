import { randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * Returns a copy of `sourcePath` with a random UUID appended after its
 * content. JPEG decoders (including Pillow's, which the worker uses) stop
 * at the EOI marker and ignore trailing bytes, so the image itself is
 * unaffected — but its SHA-256 changes, giving each E2E run its own image
 * identity. Without this, re-running the suite against the same persisted
 * Postgres/MinIO volumes would hit the *real* duplicate-image protection
 * from a previous run, not a fresh upload.
 */
export function uniqueFixtureCopy(sourcePath: string): string {
  const original = readFileSync(sourcePath);
  const unique = Buffer.concat([original, Buffer.from(randomUUID())]);
  const dir = mkdtempSync(path.join(os.tmpdir(), "bv2-e2e-"));
  const target = path.join(dir, path.basename(sourcePath));
  writeFileSync(target, unique);
  return target;
}

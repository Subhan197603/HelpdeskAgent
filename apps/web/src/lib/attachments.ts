import type { apiClient } from "./api";
import { newIdempotencyKey, unwrap } from "./api";

export async function uploadTicketAttachment(
  client: ReturnType<typeof apiClient>,
  ticketKey: string,
  file: File,
  visibility: "INTERNAL" | "PUBLIC",
) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer(),
  );
  const checksum = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  const authorization = unwrap(
    await client.POST("/api/v1/tickets/{ticket_key}/attachments/uploads", {
      params: { path: { ticket_key: ticketKey } },
      body: {
        content_type: file.type || "application/octet-stream",
        file_size_bytes: file.size,
        filename: file.name,
        sha256_checksum: checksum,
        visibility,
      },
    }),
  );
  const upload = await fetch(authorization.upload_url, {
    body: file,
    headers: authorization.upload_headers,
    method: "PUT",
  });
  if (!upload.ok)
    throw new Error("The attachment could not be transferred to quarantine.");
  return unwrap(
    await client.POST("/api/v1/attachments/{attachment_id}/finalize", {
      params: {
        header: { "Idempotency-Key": newIdempotencyKey("attachment-finalize") },
        path: { attachment_id: authorization.attachment_id },
      },
    }),
  );
}

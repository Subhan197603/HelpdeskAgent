import { useState, type SyntheticEvent } from "react";

import { apiClient } from "../lib/api";
import { uploadTicketAttachment } from "../lib/attachments";
import { StatusBadge } from "./Badges";
import { ErrorState } from "./States";

export function AttachmentStatus({
  filename,
  status,
}: {
  filename: string;
  status: "CLEAN" | "ERROR" | "INFECTED" | "QUARANTINED" | "SCANNING";
}) {
  return (
    <div className="attachment-result">
      <strong>{filename}</strong>
      <StatusBadge status={status} />
    </div>
  );
}

export function AttachmentUploader({
  analyst,
  client,
  ticketKey,
}: {
  analyst: boolean;
  client: ReturnType<typeof apiClient>;
  ticketKey: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [visibility, setVisibility] = useState<"INTERNAL" | "PUBLIC">("PUBLIC");
  const [state, setState] = useState<
    "idle" | "uploading" | "CLEAN" | "ERROR" | "INFECTED"
  >("idle");
  const [error, setError] = useState<string | null>(null);
  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setState("uploading");
    try {
      const result = await uploadTicketAttachment(
        client,
        ticketKey,
        file,
        visibility,
      );
      setState(result.scan_status);
    } catch {
      setState("ERROR");
      setError("The file could not be uploaded and scanned. Try again later.");
    }
  }
  return (
    <section
      className="attachment-uploader"
      aria-labelledby="attachments-heading"
    >
      <h2 id="attachments-heading">Attachments</h2>
      <p>
        Files remain unavailable until malware scanning completes successfully.
      </p>
      {error && (
        <ErrorState description={error} title="Attachment unavailable" />
      )}
      {state !== "idle" && state !== "uploading" && (
        <AttachmentStatus
          filename={file?.name ?? "Attachment"}
          status={state}
        />
      )}
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label htmlFor="ticket-attachment">Choose a file</label>
        <input
          id="ticket-attachment"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
          }}
          type="file"
        />
        {analyst && (
          <label
            className="attachment-visibility"
            htmlFor="attachment-visibility"
          >
            Visibility
            <select
              id="attachment-visibility"
              onChange={(event) => {
                setVisibility(event.target.value as "INTERNAL" | "PUBLIC");
              }}
              value={visibility}
            >
              <option value="PUBLIC">Employee and analysts</option>
              <option value="INTERNAL">Analysts only</option>
            </select>
          </label>
        )}
        <button
          className="button secondary"
          disabled={!file || state === "uploading"}
          type="submit"
        >
          {state === "uploading"
            ? "Uploading and scanning…"
            : "Upload attachment"}
        </button>
      </form>
    </section>
  );
}

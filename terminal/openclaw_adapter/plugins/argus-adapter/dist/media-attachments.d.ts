export type AttachmentDescriptor = {
    path?: string;
    url?: string;
    name: string;
    mime_type?: string;
};
export declare function basename(value: string): string;
export declare function mimeFromName(name: string): string | undefined;
export declare function mediaUriName(uri: string): string;
/** Parse webchat / QQ media markers out of the user prompt. */
export declare function parsePromptAttachments(prompt: string): AttachmentDescriptor[];
export declare function resolveMediaRoot(cfg: {
    mediaRoot?: string;
}): string;
/** Resolve a media://inbound/<id> URI to a local path inside mediaRoot. */
export declare function resolveMediaUri(uri: string, mediaRoot: string): string | null;
/**
 * OpenClaw wraps media-bearing prompts in a transport envelope
 * ("Conversation info (untrusted metadata):" + a ```json block + a
 * "[User sent media without caption]" line). It is gateway scaffolding,
 * not user input, but the semantic classifier flags the "untrusted
 * metadata" phrase as prompt injection. Strip it before checking while
 * keeping real user text and media marker lines.
 */
export declare function stripGatewayEnvelope(prompt: string): string;
/** Extract attachments captured on message_received from event.metadata. */
export declare function attachmentsFromMetadata(meta: unknown): AttachmentDescriptor[];

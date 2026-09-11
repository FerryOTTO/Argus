export type TextPart = {
    type: "text";
    text: string;
    [key: string]: unknown;
};
export type MessageLike = {
    content?: unknown;
};
export declare function replaceMessageText(value: unknown, text: string): unknown;

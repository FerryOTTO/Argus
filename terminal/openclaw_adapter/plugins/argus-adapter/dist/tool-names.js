const TOOL_NAME_MAP = {
    read: "read_file",
    write: "write_file",
    edit: "write_file",
    exec: "execute_bash",
    web_fetch: "http_request",
    web_search: "web_search",
};
export function normalizeToolName(toolName) {
    return TOOL_NAME_MAP[toolName] ?? toolName;
}

# Extract conversational turns from a Claude Code session JSONL tail.
# User messages carry tool_result blocks for command output — those are NOT
# user prompts. Assistant tool_use-only turns have no text and are omitted.
[.[] | select(.type == "assistant" or .type == "user") |
  if .type == "assistant" then
    {
      role: "assistant",
      content: ([.message.content[]? | select(.type == "text") | .text] | join("\n")),
      source_id: (.uuid // .message.id // null),
      occurred_at: (.timestamp // null)
    }
  elif .type == "user" then
    (
      if (.message.content | type) == "array" then
        ([.message.content[]? | select(.type == "text") | .text] | join("\n"))
      else
        (.message.content // "" | tostring)
      end
    ) as $text |
    if $text != "" then
      {
        role: "user",
        content: $text,
        source_id: (.uuid // .message.id // null),
        occurred_at: (.timestamp // null)
      }
    else empty end
  else
    empty
  end
] | map(select(.content != ""))

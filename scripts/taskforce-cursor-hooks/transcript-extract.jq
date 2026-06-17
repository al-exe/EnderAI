# Extract conversational turns from a session JSONL tail.
# Claude Code uses ``.type``; Cursor uses ``.role``. User messages carry
# tool_result blocks for command output — those are NOT user prompts.
# Assistant tool_use-only turns have no text and are omitted.
def turn_role:
  if (.type // "") == "assistant" or (.type // "") == "user" then .type
  elif (.role // "") == "assistant" or (.role // "") == "user" then .role
  else empty
  end;

[.[] | select(turn_role != null) |
  if turn_role == "assistant" then
    {
      role: "assistant",
      content: ([.message.content[]? | select(.type == "text") | .text] | join("\n")),
      source_id: (.uuid // .message.id // null),
      occurred_at: (.timestamp // null)
    }
  elif turn_role == "user" then
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

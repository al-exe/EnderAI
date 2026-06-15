# Bash commands from assistant tool_use blocks, paired with tool_result output.
. as $all |
[
  $all[]
  | select(.type == "user")
  | .message.content[]?
  | select(.type == "tool_result" and (.tool_use_id // "") != "")
  | {
      key: .tool_use_id,
      value: (
        .content
        | if type == "array" then ([.[] | (.text // tostring)] | join("\n")) else tostring end
      )
    }
] | from_entries as $results |
[
  $all[]
  | select(.message?.content?[]? | (.type == "tool_use" and .name == "Bash"))
  | . as $turn
  | .message.content[]
  | select(.type == "tool_use" and .name == "Bash")
  | {
      cmd: (
        (.input.command // "")
        | if length > 2000 then .[:1997] + "..." else . end
      ),
      exit_code: null,
      source_id: (.id // null),
      occurred_at: ($turn.timestamp // null),
      output: (
        (if (.id // "") == "" then null else $results[.id] end)
        | if . == null then null elif length > 4000 then .[:3997] + "..." else . end
      )
    }
] | map(select(.cmd != ""))

#!/bin/bash

# Read the hook event from standard input.
EVENT=$(cat)

# Extract the requested Bash command.
COMMAND=$(echo "$EVENT" | jq -r '.tool_input.command')

# Reject commands containing "rm ".
if echo "$COMMAND" | grep -q "rm "; then
  echo "Blocked: deleting files is not allowed in this project" >&2
  exit 2
fi

# Permit everything else.
exit 0

#!/usr/bin/env bash
# SEGMENT 4: MCP + A2A. Needs ELASTIC_API_KEY and KB_URL exported.
set -euo pipefail
H=(-H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" -H "Content-Type: application/json")
echo "== A2A agent card =="; curl -s "${H[@]}" "$KB_URL/api/agent_builder/a2a/elastic-ai-agent.json" | python3 -m json.tool | head -40
echo "== A2A message/send =="
curl -s "${H[@]}" -X POST "$KB_URL/api/agent_builder/a2a/elastic-ai-agent" -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"kind":"text","text":"Find an ergonomic office chair under $500 and cite the product."}]}}}' | python3 -m json.tool | head -40
echo "== MCP tools/list =="
curl -s "${H[@]}" -H "Accept: application/json, text/event-stream" -X POST "$KB_URL/api/agent_builder/mcp" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 1500
echo
echo "== Claude Code MCP config (run once) =="
echo "claude mcp add --transport http elastic-demo $KB_URL/api/agent_builder/mcp --header \"Authorization: ApiKey \$ELASTIC_API_KEY\""

import json
import os
import sys
import time

# Simple MCP server implementing the stdio transport for the Gemini CLI.
# This server allows Gemini to check for new messages during long-running tasks.

def wait(seconds: int):
    """Sleeps for a specific number of seconds."""
    time.sleep(seconds)
    return {"status": f"waited {seconds} seconds"}

def get_conversation_history(limit=20):
    """Returns the last [limit] messages from messages.json."""
    try:
        messages_path = os.path.join(os.path.dirname(__file__), "messages.json")
        if not os.path.exists(messages_path):
            return {"messages": []}
            
        with open(messages_path, "r") as f:
            data = json.load(f)
            
        # Sort by timestamp and filter for user messages
        data.sort(key=lambda m: float(m.get("timestamp", 0)))
        user_messages = [m for m in data if m.get("source") == "user"]
        
        history = user_messages[-limit:] if limit > 0 else user_messages
        return {"messages": history}
    except Exception as e:
        return {"error": str(e)}

def get_new_messages(since_timestamp):
    """Checks the messages.json file for any user messages after the given timestamp."""
    try:
        messages_path = os.path.join(os.path.dirname(__file__), "messages.json")
        if not os.path.exists(messages_path):
            return {"messages": []}
            
        with open(messages_path, "r") as f:
            data = json.load(f)
            
        new_msgs = [
            m for m in data 
            if m.get("source") == "user" and float(m.get("timestamp", 0)) > float(since_timestamp)
        ]
        return {"messages": new_msgs}
    except Exception as e:
        return {"error": str(e)}

def main():
    # Basic JSON-RPC style loop for MCP via stdio
    # Since we can't install the 'mcp' lib, we handle the protocol ourselves.
    
    while True:
        line = sys.stdin.readline()
        if not line:
            break
            
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            # MCP Protocol Handshake
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "discord-interruption-server", "version": "0.1.0"}
                    }
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "get_new_messages",
                                "description": "Checks for new user messages in Discord that arrived after a specific timestamp. Use this to see if the user has provided new instructions or feedback while you are working.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "since_timestamp": {
                                            "type": "number",
                                            "description": "The epoch timestamp (seconds) to check from."
                                        }
                                    },
                                    "required": ["since_timestamp"]
                                }
                            },
                            {
                                "name": "get_conversation_history",
                                "description": "Returns the recent conversation history from Discord. Use this to get context on what has been discussed previously.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "limit": {
                                            "type": "number",
                                            "description": "The number of messages to retrieve (defaults to 20)."
                                        }
                                    }
                                }
                            },
                            {
                                "name": "wait",
                                "description": "Pauses execution for a specified number of seconds. Use this in a loop with get_new_messages() to wait for user confirmation without exiting.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "seconds": {
                                            "type": "number",
                                            "description": "Number of seconds to sleep."
                                        }
                                    },
                                    "required": ["seconds"]
                                }
                            }
                        ]
                    }
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                
                if tool_name == "get_new_messages":
                    since = tool_args.get("since_timestamp", 0)
                    result = get_new_messages(since)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result)}]
                        }
                    }
                elif tool_name == "get_conversation_history":
                    limit = tool_args.get("limit", 20)
                    result = get_conversation_history(limit)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result)}]
                        }
                    }
                elif tool_name == "wait":
                    seconds = tool_args.get("seconds", 1)
                    result = wait(seconds)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result)}]
                        }
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                    }
            else:
                # Basic implementations of other methods for compatibility
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {}
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            
        except Exception as e:
            # Silently ignore malformed lines for stdio robustness
            continue

if __name__ == "__main__":
    main()

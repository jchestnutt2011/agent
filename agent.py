# A minimal local AI agent with one tool
import ollama

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Look up the current price of an item",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"}
                },
                "required": ["item"]
            }
        }
    }
]

def get_price(item):
    prices = {"apple": "$1.20", "bread": "$3.50", "milk": "$2.80"}
    return prices.get(item.lower(), f"No price found for {item}")

messages = [{"role": "user", "content": "How much does bread cost?"}]

while True:
    response = ollama.chat(
        model="qwen2.5:7b-instruct",
        messages=messages,
        tools=tools
    )
    msg = response["message"]
    messages.append(msg)

    if not msg.get("tool_calls"):
        print("\nAgent:", msg["content"])
        break

    for call in msg["tool_calls"]:
        args = call["function"]["arguments"]
        result = get_price(**args)
        print(f"[Tool: get_price({args}) → {result}]")
        messages.append({"role": "tool", "content": result})
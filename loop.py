import os , json,httpx
import openai
from openai import OpenAI
import dotenv

dotenv.load_dotenv()

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0")),
    timeout=30,
)

tools = [{
    "type":"function",
    "function":{
        "name":"get_order_count",
        "description":"return how many orders a customer has placed. use when the user asks about a cutomers's order count",
        "parameters":{
            "type":"object",
            "properties":{
                "customer_name":{
                    "type":"string",
                    "description":"full name of The name of the customer,e.g. 'rsha Rao'"
                }
            },
            "required":["customer_name"]
        },
    },
}]

#fake database
ORDERS = {"Asha Rao": 5, "John Doe": 3, "Jane Smith": 8}

# the real function that will be called by the tool
def get_order_count(customer_name: str):
    # look up the order count in the fake database
    order_count = ORDERS.get(customer_name, 0)
    print("order_count:", repr(order_count))
    return {"order_count": order_count}

messages = [{ "role": "user", "content": "how many orders has Asha Rao and Jane Smith placed?" }]

MAX_Turns = 2

for i in range(MAX_Turns):
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=tools,
    )

    msg = resp.choices[0].message
    messages.append(msg)
    if resp.choices[0].finish_reason != "tool_calls":
       print(msg.content); break #final answer
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        print(repr(args))
        result = get_order_count(**args)
        messages.append({"role": "tool",
                         "tool_call_id":tc.id,
                         "content": repr(result)
                         })
    
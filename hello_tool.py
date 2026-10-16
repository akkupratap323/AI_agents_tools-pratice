import os ,json,httpx

from dotenv import load_dotenv
import openai
from openai import OpenAI

load_dotenv()

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
                    "description":"full name of The name of the customer,e.g. 'asha rao'"
                }
            },
            "required":["customer_name"]
        },
    },
}]

response = client.chat.completions.create(
    model="deepseek-chat",
    
    messages=[{"role": "user", "content": "how many orders has asha rao placed?"}],
    tools=tools,
)

print("response:",response)

choice = response.choices[0]

print("finish_reason:",choice.finish_reason)

for tc in choice.message.tool_calls or []:
    print("id:",tc.id)
    print("name:",tc.function.name)
    print("raw arguments (a string):" , repr(tc.function.arguments))
    print("parsed:" , json.loads(tc.function.arguments))
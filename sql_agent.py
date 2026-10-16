import os,json,httpx
import sqlite3
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

con = sqlite3.connect("file:shop.db?mode=ro" , uri=True)

def list_tables():
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    
    return [d[0] for d in cur.fetchall()]
   

def get_describe_table(table_name):
    valid = list_tables()
    if table_name not in valid:
         return{"error":"unknown_table",
                "message": f"No table named{table_name!r}.",
                "available_tables": valid,
                "hint":"use one of the available table names exactly as listed" }
    rows = con.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {"table":table_name, "columns":[{"name":r[1], "type":r[2], "nullable":not r[3]} for r in rows]}

MAX_ROWS = 50
def run_query(sql):
    cur = con.cursor()
    cur.execute(sql)

    if cur.description is None:
         return {"error":"not_a_select","message":"only select queries are allowed"}
    
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(MAX_ROWS+1)
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    result =  {"columns":cols, "rows":rows, "row_count": len(rows), "truncated":truncated}
    if truncated:
         result["note"] = (f"Returns at most 50 rows. If `truncated` is true there were more rows; use COUNT/SUM/GROUP BY or WHERE instead of reading raw rows."
)
    return result



# print(list_tables())
# print(get_describe_table("customers"))
# print(run_query("SELECT * FROM customers LIMIT 5;"))



TOOL_HANDERS = {
    "list_tables": list_tables,
    "describe_table": get_describe_table,
    "run_query": run_query,
}

TOOLS =[
    {
     "type":"function",
        "function":{
            "name":"list_tables",
            "description":"list all tables in the database . call this first if u don't know the table names",
            "parameters":{"type":"object", "properties":{}},
        }   
    },
    {
        "type":"function",
        "function":{
            "name":"describe_table",
            "description":"describe a table in the database. call this after list_tables to get the column names and types",
            "parameters":{"type":"object",
                        "properties":{
                            "table_name":{
                                "type":"string",
                                "description":"the name of the table to describe"
                                         }
                                      },
                        "required":["table_name"]
                        },
                  },
    
    },
    {
        "type":"function",
        "function":{
            "name":"run_query",
            "description":"run a sql query on the database. call this after describe_table to get the column names and types",
            "parameters":{"type":"object",
                        "properties":{
                            "sql":{
                                "type":"string",
                                "description":"the sql query to run and maxcap on results is 50"
                                         }
                                      },
                        "required":["sql"]
                        },
                  },
      
    },

]

MAX_TURNS = 8

def run_agent (messages):
    for i in range(MAX_TURNS):
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                tools=TOOLS,
            )
    
            msg = resp.choices[0].message
            messages.append(msg)
    
            if resp.choices[0].finish_reason != "tool_calls":
                return msg.content
            
            print(f"\n[turn{i}] answer:{msg.content}") 
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                print(f"\n[turn {i}] CALL {tc.function.name} {args}")
    
                handler = TOOL_HANDERS.get(tc.function.name)
    
                def safe_call(handler,**args):
                    try:
                        return handler(**args)
                    except Exception as e:
                        print(f"[turn {i}] ERROR {type(e).__name__} - {e}")
                        return {"error":str(e)}
               
                result =  safe_call(handler,**args)
                print(f"[turn {i}] RESULT {str(result)} ")
                messages.append({"role":"tool", "tool_call_id":tc.id, "content":json.dumps(result)})
    else :
            return print("stopped hit max turns")   

system_promt = "you answer questiosn about a shop database(sqlite3) with tables customers, products, orders, order_items. you can use the tools list_tables, describe_table, run_query to get the information you need to answer the questions. you can only use the tools if you need to get information from the database. you should not make up information. if you don't know the answer, say 'I don't know' and also case sensative items also present in database so make sure u have the context of those"

def main():
    
    messages = [{"role":"system", "content":system_promt}]
    print("shop agent. type /reset to clear memory,/exit to quit.\n")

    while True:
         try:
              question = input("you: ").strip()
         except (KeyboardInterrupt, EOFError):
              print("\nbye")
              break

         if not question:
              continue
         if question == "/exit":
              break
         if question == "/reset":
              messages = [{"role": "system", "content": system_promt}]
              print("(memory cleared)\n")
              continue

         messages.append({"role":"user","content":question })
         answer = run_agent(messages)
         print(f"\nAgent:{answer}\n")   

    
if __name__ == "__main__":
    main()
    
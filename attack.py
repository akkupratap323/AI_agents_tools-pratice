from sql_agent import list_tables, get_describe_table, run_query , TOOL_HANDERS

def attack(label, fn , *args, **kwargs):
    print(f"\n=== {label} ===")
    try:
        out = fn(*args, **kwargs)
        print("RETURNED:" , str(out)[:300])
        return out
    except Exception as e:
        print("CRASHED:",type(e).__name__,"-",e)
        return None

# attack("1 typo in query",run_query,"slect * from orders")
attack("7 wrong arg name" )
import asyncio, aiosqlite

async def check():
    async with aiosqlite.connect('./data/llull.db') as db:
        cur = await db.execute(
            "SELECT id, role, substr(content, 1, 300), created_at FROM conversations WHERE topic_id='0e71f9af-23df-460b-ac9a-6f3356c23020' ORDER BY created_at"
        )
        rows = await cur.fetchall()
        print(f"Total messages: {len(rows)}\n")
        for r in rows:
            print(f"[{r[3]}] {r[1].upper()} ({r[0][:8]})")
            print(f"  {repr(r[2])}")
            print()

asyncio.run(check())

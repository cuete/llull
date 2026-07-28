"""Delete all conversation history for the test topic."""
import asyncio, aiosqlite

TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020"

async def clean():
    async with aiosqlite.connect('./data/llull.db') as db:
        cur = await db.execute("SELECT COUNT(*) FROM conversations WHERE topic_id=?", (TOPIC_ID,))
        count = (await cur.fetchone())[0]
        await db.execute("DELETE FROM conversations WHERE topic_id=?", (TOPIC_ID,))
        await db.commit()
        print(f"Deleted {count} messages from topic {TOPIC_ID}")

asyncio.run(clean())

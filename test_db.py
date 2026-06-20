import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def test():
    try:
        conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
        
        # Test connection
        result = await conn.fetch("SELECT 1 as test")
        print("✅ Database connected!")
        
        # List tables
        tables = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        print(f"✅ {len(tables)} tables created")
        for t in tables[:10]:
            print(f"   - {t['table_name']}")
        
        # Test guild_settings
        settings = await conn.fetch("SELECT * FROM guild_settings")
        print(f"✅ guild_settings: {len(settings)} rows")
        
        await conn.close()
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

import asyncio
asyncio.run(test())
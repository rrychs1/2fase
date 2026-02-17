import asyncio
from orchestration.bot_runner import BotRunner

if __name__ == "__main__":
    runner = BotRunner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")

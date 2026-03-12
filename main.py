import asyncio
from dotenv import load_dotenv
from config.validation import validate_config
from orchestration.bot_runner import BotRunner

if __name__ == "__main__":
    load_dotenv()
    validate_config()  # exits with clear error if config is broken

    runner = BotRunner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")


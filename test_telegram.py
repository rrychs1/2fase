
import asyncio
import os
from dotenv import load_dotenv
from logging_monitoring.telegram_bot import TelegramBot

# Load env vars
load_dotenv()

async def test():
    print("--- Probando Telegram ---")
    token = os.getenv('TELEGRAM_TOKEN')
    print(f"Token leído: {token[:5]}...{token[-5:] if token else 'None'}")
    
    bot = TelegramBot()
    if bot.enabled:
        print("Intentando enviar mensaje...")
        try:
            await bot.send_message("🔔 **Prueba de Conexión**\nSi lees esto, el bot está conectado correctamente.")
            print("✅ Mensaje enviado con éxito.")
        except Exception as e:
            print(f"❌ Error al enviar: {e}")
    else:
        print("❌ Telegram no habilitado en .env")

if __name__ == "__main__":
    asyncio.run(test())

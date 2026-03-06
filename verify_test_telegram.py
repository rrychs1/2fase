
import asyncio
import os
import logging
from dotenv import load_dotenv
from logging_monitoring.telegram_bot import TelegramBot

# Setup simple logging
logging.basicConfig(level=logging.INFO)
load_dotenv()

async def test():
    print("--- Verificando Identidad Del Bot ---")
    bot = TelegramBot()
    if bot.enabled:
        print("Conectando con Telegram API...")
        username = await bot.verify_bot()
        if username:
            print(f"\n✅ ¡ÉXITO! El bot es: @{username}")
            print(f"👉 Ve a Telegram y busca: @{username}")
            print("   Si no ves mensajes, dale al botón 'START' o escribe /start")
            
            await bot.send_message(f"🔔 Confirmación de identidad: Soy @{username}")
            print("   Mensaje de prueba enviado.")
        else:
            print("❌ No se pudo verificar la identidad.")
    else:
        print("❌ Telegram no configurado en .env")

if __name__ == "__main__":
    asyncio.run(test())

import os
# import requests  # Eliminar esta línea ya que no lo usamos
import logging
import time
import sys
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    filters,
    ContextTypes
)
from openai import OpenAI, AzureOpenAI
from dotenv import load_dotenv
import httpx
from datetime import datetime, date

# Configurar logging más detallado
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout  # Asegura que los logs van a stdout
)

# Reemplaza con tu token de bot de Telegram
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Configuración de OpenAI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# ID del asistente
ASSISTANT_ID = os.getenv('ASSISTANT_ID')

# Inicializamos el cliente de OpenAI con la configuración correcta
client = OpenAI(
    api_key=OPENAI_API_KEY,
)

# Configuramos el cliente HTTP personalizado
http_client = httpx.Client(
    timeout=60.0,
    headers={
        "OpenAI-Beta": "assistants=v2"
    }
)

# Asignamos el cliente HTTP personalizado
client.http_client = http_client

# Diccionario para almacenar los hilos de conversación por usuario
user_threads = {}

# Definición de planes
SUBSCRIPTION_PLANS = {
    "FREE": {
        "name": "Plan básico gratuito",
        "daily_messages": 3,
        "tokens_per_day": 2000,
        "price": 0
    },
    "BASIC": {
        "name": "Plan básico",
        "daily_messages": 10,
        "tokens_per_day": 5000,
        "price": 2.99
    },
    "PREMIUM": {
        "name": "Plan premium",
        "daily_messages": 20,
        "tokens_per_day": 10000,
        "price": 6.99
    }
}

# Estructura para rastrear el uso diario
class UserUsage:
    def __init__(self):
        self.date = date.today()
        self.message_count = 0
        self.token_count = 0

# Diccionario para almacenar el uso diario por usuario
user_usage = {}

# Estructura para almacenar los planes de los usuarios
user_plans = {}  # user_id -> {"plan": "FREE", "expiry": datetime}

def get_user_usage(user_id: int) -> UserUsage:
    """Obtiene o crea el registro de uso del usuario para el día actual"""
    today = date.today()
    
    # Si no existe el usuario o es un día nuevo, crear nuevo registro
    if user_id not in user_usage or user_usage[user_id].date != today:
        user_usage[user_id] = UserUsage()
    
    return user_usage[user_id]

def get_user_plan(user_id: int) -> str:
    """Obtiene el plan actual del usuario"""
    if user_id not in user_plans or user_plans[user_id]["expiry"] < datetime.now():
        return "FREE"
    return user_plans[user_id]["plan"]

def can_send_message(user_id: int) -> bool:
    """Verifica si el usuario puede enviar más mensajes hoy"""
    usage = get_user_usage(user_id)
    plan_type = get_user_plan(user_id)
    plan = SUBSCRIPTION_PLANS[plan_type]
    return usage.message_count < plan["daily_messages"]

# Añadir verificación de variables de entorno
def verify_env_variables():
    required_vars = ['BOT_TOKEN', 'OPENAI_API_KEY', 'ASSISTANT_ID']
    for var in required_vars:
        if not os.getenv(var):
            logging.error(f"Missing environment variable: {var}")
            sys.exit(1)
        else:
            logging.info(f"Found environment variable: {var}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja errores del bot."""
    logging.error(f"Exception while handling an update: {context.error}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se ejecuta cuando el usuario usa /start"""
    await update.message.reply_text(
        "¡Hola! Soy un asistente especializado en los síntomas de la ansiedad DPDR (despersonalización y desrealización). "
        "Puedo ayudarte con información y consejos basados en guías y recursos especializados.\n\n"
        "📌 Comandos disponibles:\n"
        "/faq - Ver categorías principales\n"
        "/help - Ver todos los comandos\n"
        "/plan - Ver tu plan actual y límites\n"
        "/reset - Reiniciar conversación\n\n"
        "¿En qué puedo ayudarte?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Maneja cualquier mensaje de texto del usuario """
    user_id = update.effective_user.id
    user_text = update.message.text.lower()  # Convertimos a minúsculas

    # Verificar límites de uso
    if not can_send_message(user_id):
        await update.message.reply_text(
            "Has alcanzado tu límite diario de mensajes. 🚫\n"
            "Usa /plan para ver los planes disponibles y sus límites."
        )
        return

    # Actualizar contador de mensajes
    usage = get_user_usage(user_id)
    usage.message_count += 1

    # Lista de respuestas de cortesía que no requieren procesamiento
    cortesia = ["de nada", "gracias", "ok", "vale", "👍", "👎"]
    
    # Verificamos si es un feedback o un mensaje de sistema
    if user_text in ["👍 útil", "👎 no útil", "❓ nueva pregunta"]:
        if user_text == "👍 útil":
            await update.message.reply_text("¡Gracias por tu feedback positivo!")
        elif user_text == "👎 no útil":
            await update.message.reply_text("Gracias por tu feedback. ¿Podrías decirme cómo puedo mejorar?")
        return
    
    # Si es un mensaje de cortesía, no procesamos ni pedimos feedback
    if user_text in cortesia:
        return

    try:
        # Crear o recuperar el hilo de conversación del usuario
        if user_id not in user_threads:
            user_threads[user_id] = client.beta.threads.create()
        
        thread = user_threads[user_id]

        # Manejo especial para las categorías del FAQ
        if user_text in ["ayuda a entenderme", "Ayuda a Entenderme".lower()]:
            instructions = (
                "Proporciona una explicación del DPDR para familiares y amigos usando exactamente este formato y estructura:\n\n"
                "1. ¿Qué es DPDR?\n"
                "Explica que es una respuesta de defensa del cerebro ante la ansiedad/estrés. "
                "Usa la analogía de ver la vida a través de una pantalla de TV o un cristal, "
                "enfatizando que no es peligroso ni permanente.\n\n"
                "2. ¿Por qué ocurre?\n"
                "Explica la respuesta de congelación como mecanismo de protección natural, "
                "similar a cuando el cerebro se 'desconecta' temporalmente para protegerse.\n\n"
                "3. ¿Cómo se siente?\n"
                "Describe las sensaciones usando ejemplos cotidianos como: sentirse como en un sueño despierto, "
                "o como si estuvieras viendo una película de tu propia vida.\n\n"
                "4. ¿Es real o está solo en mi cabeza?\n"
                "Valida la experiencia pero enfatiza su temporalidad.\n\n"
                "5. ¿Cómo puedo apoyar a alguien con DPDR?\n"
                "Lista de formas prácticas de apoyo.\n\n"
                "6. La recuperación es posible\n"
                "Mensaje esperanzador sobre la recuperación.\n\n"
                "7. Conclusión\n"
                "Agradecimiento y recordatorio final positivo.\n\n"
                "Mantén el mismo tono tranquilizador y empático, usando analogías naturales y cotidianas."
            )
            # Añadimos el contenido específico para esta opción
            user_text = "Explica qué es el DPDR de manera tranquilizadora para familiares y amigos"
        elif user_text == "entender dpdr":
            instructions = (
                "Proporciona una explicación general del DPDR como un mecanismo de protección del cerebro ante el estrés, "
                "enfatizando su naturaleza temporal y tratable. Incluye una breve explicación de su origen como respuesta "
                "natural de protección, pero mantén un tono informativo y tranquilizador."
            )
        else:
            instructions = "Proporciona respuestas concisas y específicas sobre DPDR."

        # Añadir el mensaje del usuario al hilo
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_text
        )

        # Ejecutar el asistente
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
            model="gpt-4-turbo-preview",  # Modelo más eficiente
            temperature=0.7,  # Más enfocado
            instructions=instructions
        )

        # Informar al usuario que estamos procesando
        await update.message.reply_text("Procesando tu pregunta, por favor espera...")

        # Esperar a que el asistente complete la respuesta con timeout
        start_time = time.time()
        completed = False
        
        while not completed and (time.time() - start_time) < 300:  # 5 minutos máximo
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            
            if run_status.status == 'completed':
                completed = True
                break
            elif run_status.status == 'failed':
                raise Exception(f"Error del asistente: {run_status.last_error}")
            
            time.sleep(2)  # Esperamos 2 segundos entre checks

        if not completed:
            raise TimeoutError("El asistente tardó demasiado en responder")

        # Obtener los mensajes del hilo
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        
        # Obtener la última respuesta del asistente
        assistant_response = messages.data[0].content[0].text.value

    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")
        assistant_response = f"Lo siento, hubo un error al procesar tu mensaje: {str(e)}"
        # Limpiar el hilo si hay un error
        if user_id in user_threads:
            del user_threads[user_id]

    # Respondemos al usuario con el texto del asistente
    await update.message.reply_text(assistant_response)
    
    # Solo añadimos feedback para respuestas sustanciales (no para mensajes de sistema)
    if not any(keyword in user_text for keyword in ["útil", "gracias", "ok", "vale"]):
        keyboard = [["👍 Útil", "👎 No útil", "❓ Nueva pregunta"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(
            "¿Te ha resultado útil esta respuesta?",
            reply_markup=reply_markup
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la ayuda del bot"""
    await update.message.reply_text(
        "Comandos disponibles:\n"
        "/start - Inicia el bot\n"
        "/help - Muestra esta ayuda\n"
        "/reset - Reinicia tu conversación\n"
        "\nPuedes preguntarme cualquier cosa sobre DPDR y despersonalización."
    )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reinicia la conversación del usuario"""
    user_id = update.effective_user.id
    if user_id in user_threads:
        del user_threads[user_id]
    await update.message.reply_text(
        "He reiniciado tu conversación. Puedes empezar de nuevo."
    )

async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra categorías de preguntas frecuentes"""
    keyboard = [
        ["Entender DPDR", "Síntomas"],
        ["Tratamientos", "Ejercicios"],
        ["Ayuda a Entenderme", "Recursos"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "Selecciona una categoría:\n\n"
        "💡 'Entender DPDR' te da una visión general del trastorno.\n"
        "❤️ 'Ayuda a Entenderme' está pensado para compartir con familiares y "
        "amigos, ayudándoles a comprender mejor tu experiencia.",
        reply_markup=reply_markup
    )

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite al usuario dar retroalimentación"""
    keyboard = [["👍 Útil", "👎 No útil"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "¿Te fue útil mi última respuesta?",
        reply_markup=reply_markup
    )

async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra opciones para actualizar el plan"""
    keyboard = [
        ["💎 Plan Basic - 2.99€/mes"],
        ["👑 Plan Premium - 6.99€/mes"],
        ["❌ Cancelar"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text(
        "Selecciona el plan al que quieres actualizar:\n\n"
        "💎 Plan Basic (2.99€/mes):\n"
        "- 10 mensajes/día\n"
        "- 5000 tokens/día\n\n"
        "👑 Plan Premium (6.99€/mes):\n"
        "- 20 mensajes/día\n"
        "- 10000 tokens/día",
        reply_markup=reply_markup
    )

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el plan actual y los planes disponibles"""
    user_id = update.effective_user.id
    usage = get_user_usage(user_id)
    plan_type = get_user_plan(user_id)
    current_plan = SUBSCRIPTION_PLANS[plan_type]
    
    message = f"📊 Tu plan actual: {current_plan['name']}\n"
    message += f"📝 Mensajes usados hoy: {usage.message_count}/{current_plan['daily_messages']}\n"
    message += f"🔢 Tokens disponibles por día: {current_plan['tokens_per_day']}\n"
    
    if plan_type != "FREE":
        expiry = user_plans[user_id]["expiry"]
        message += f"📅 Tu suscripción vence el: {expiry.strftime('%d/%m/%Y')}\n"
    
    message += "\n💡 Planes disponibles:\n\n"
    message += "FREE:\n"
    message += "- Plan básico gratuito\n"
    message += "- 3 mensajes/día\n\n"
    message += "BASIC:\n"
    message += "- Para uso regular\n"
    message += "- 10 mensajes/día\n"
    message += "- Precio: 2.99€/mes\n\n"
    message += "PREMIUM:\n"
    message += "- Para uso intensivo\n"
    message += "- 20 mensajes/día\n"
    message += "- Precio: 6.99€/mes\n\n"
    
    if plan_type == "FREE":
        message += "\n🌟 Usa /upgrade para mejorar tu plan"
    
    await update.message.reply_text(message)

def main():
    logging.info("Starting bot...")
    verify_env_variables()
    
    try:
        application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .concurrent_updates(False)  # Cambiado a False
            .build()
        )
        
        # Registramos el manejador de errores
        application.add_error_handler(error_handler)

        # Registramos los handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("faq", faq_command))
        application.add_handler(CommandHandler("feedback", feedback_command))
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("upgrade", upgrade_command))
        
        # Handler para mensajes de texto
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logging.info("Bot initialized successfully")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],  # Específico
            stop_signals=None,
            close_loop=False
        )
    except Exception as e:
        logging.error(f"Critical error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()

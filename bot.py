import os
import requests
import logging
import time
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    filters,
    ContextTypes
)
from openai import OpenAI
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Reemplaza con tu token de bot de Telegram
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Configuración de OpenAI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# ID del asistente
ASSISTANT_ID = os.getenv('ASSISTANT_ID')

# Inicializamos el cliente de OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Diccionario para almacenar los hilos de conversación por usuario
user_threads = {}

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
        "/reset - Reiniciar conversación\n\n"
        "¿En qué puedo ayudarte?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Maneja cualquier mensaje de texto del usuario """
    user_id = update.effective_user.id
    user_text = update.message.text.lower()  # Convertimos a minúsculas

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

def main():
    # Creamos la aplicación con un nombre único
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .arbitrary_callback_data(False)  # Desactivamos el callback_data cache
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
    
    # Handler para mensajes de texto
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Iniciamos el bot con configuración más básica
    logging.info("Bot iniciado")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=[],  # No permitimos actualizaciones pendientes
        stop_signals=None,   # Desactivamos señales de parada
    )

if __name__ == "__main__":
    main()

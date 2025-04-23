import os
# import requests  # Eliminar esta línea ya que no lo usamos
import logging
import time
import sys
import sqlite3 # <-- Añadir importación
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
import httpx
from datetime import datetime, date, timedelta # <-- Añadir timedelta

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

# Configuración de la base de datos SQLite <-- NUEVO
DB_PATH = 'dpdr_bot.db'

# Inicializamos el cliente de OpenAI
client = OpenAI(
    default_headers={"OpenAI-Beta": "assistants=v2"}
)

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

# Lista de IDs de administradores
ADMIN_IDS = [
    23684095  # Admin principal
]

# --- Funciones de Base de Datos SQLite --- <-- NUEVO
def init_db():
    """Inicializa la base de datos SQLite si no existe."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Crear tabla de usuarios si no existe
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                plan TEXT DEFAULT 'FREE',
                expiry_date TEXT,
                message_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                last_reset_date TEXT
            )
        ''')
        # Crear tabla de feedback si no existe
        c.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                rating TEXT,
                timestamp TEXT
            )
        ''')
        conn.commit()
        logging.info("✅ Base de datos SQLite inicializada/verificada.")
    except sqlite3.Error as e:
        logging.error(f"❌ Error inicializando SQLite: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()

def add_user(user_id: int):
    """Añade un usuario nuevo a la base de datos si no existe."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO users (user_id, last_reset_date) VALUES (?, ?)",
                  (user_id, date.today().isoformat()))
        conn.commit()
        logging.info(f"Usuario {user_id} añadido o ya existente.")
    except sqlite3.Error as e:
        logging.error(f"Error añadiendo usuario {user_id}: {e}")
    finally:
        conn.close()

def get_user(user_id: int):
    """Obtiene los datos del usuario de la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Devuelve filas como diccionarios
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        if user_data:
            # Verificar si la fecha de último reseteo es de ayer o antes
            today = date.today()
            last_reset = date.fromisoformat(user_data['last_reset_date'])
            if last_reset < today:
                # Resetear contadores
                c.execute("UPDATE users SET message_count = 0, token_count = 0, last_reset_date = ? WHERE user_id = ?",
                          (today.isoformat(), user_id))
                conn.commit()
                # Volver a obtener los datos actualizados
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                user_data = c.fetchone()
        return user_data # Devuelve None si no se encuentra
    except sqlite3.Error as e:
        logging.error(f"Error obteniendo usuario {user_id}: {e}")
        return None
    finally:
        conn.close()

def update_user_usage(user_id: int, message_increment: int = 1, token_increment: int = 0):
    """Actualiza el uso del usuario en la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE users
            SET message_count = message_count + ?,
                token_count = token_count + ?
            WHERE user_id = ?
        ''', (message_increment, token_increment, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error actualizando uso para usuario {user_id}: {e}")
    finally:
        conn.close()

def add_feedback(user_id: int, message: str, rating: str):
    """Guarda el feedback del usuario en la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO feedback (user_id, message, rating, timestamp) VALUES (?, ?, ?, ?)",
                  (user_id, message, rating, timestamp))
        conn.commit()
        logging.info(f"Feedback guardado para usuario {user_id}: {rating}")
    except sqlite3.Error as e:
        logging.error(f"Error guardando feedback para usuario {user_id}: {e}")
    finally:
        conn.close()
    # --- Fin Funciones de Base de Datos ---

# Añadir verificación de variables de entorno
def verify_env_variables():
    """Verifica que todas las variables de entorno necesarias estén presentes"""
    # Eliminamos la verificación de MONGO_URI
    required_vars = {
        'BOT_TOKEN': 'Token del bot de Telegram',
        'OPENAI_API_KEY': 'API key de OpenAI',
        'ASSISTANT_ID': 'ID del asistente de OpenAI'
    }
    for var, description in required_vars.items():
        if not os.getenv(var):
            logging.error(f"Missing environment variable: {var} - {description}")
            sys.exit(1)
        else:
            logging.info(f"Found environment variable: {var}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja errores del bot."""
    logging.error(f"Exception while handling an update: {context.error}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se ejecuta cuando el usuario usa /start"""
    user_id = update.effective_user.id
    add_user(user_id) # <-- Añadir usuario a la BD al iniciar
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
    user_text = update.message.text # Ya no lo ponemos en minúsculas aquí

    # --- Lógica de Límites con SQLite --- <-- MODIFICADO
    user_data = get_user(user_id)
    if not user_data:
         # Si por alguna razón el usuario no está en la BD (aunque start debería añadirlo)
        add_user(user_id)
        user_data = get_user(user_id)
        if not user_data: # Si sigue sin funcionar, hay un problema grave
             await update.message.reply_text("Error al procesar tu solicitud. Por favor, intenta usar /start de nuevo.")
             logging.error(f"No se pudo obtener/crear el usuario {user_id} en la BD.")
             return

    current_plan_type = user_data['plan'] if user_data else 'FREE'
    # Manejo de expiración de plan (si se implementa)
    if user_data and user_data['expiry_date']:
        expiry = datetime.fromisoformat(user_data['expiry_date'])
        if expiry < datetime.now():
            current_plan_type = 'FREE'
            # Podrías actualizar el plan a FREE en la BD aquí si es necesario

    plan_limits = SUBSCRIPTION_PLANS[current_plan_type]
    message_count = user_data['message_count'] if user_data else 0

    # Verificar límites (excepto admins)
    is_admin = user_id in ADMIN_IDS
    if not is_admin and message_count >= plan_limits['daily_messages']:
        await update.message.reply_text(
            "Has alcanzado tu límite diario de mensajes. 🚫\n"
            f"Tu plan '{plan_limits['name']}' permite {plan_limits['daily_messages']} mensajes al día.\n"
            "Usa /plan para ver los planes disponibles."
        )
        return
    # --- Fin Lógica de Límites ---

    # Lista de respuestas de cortesía que no requieren procesamiento
    cortesia = ["de nada", "gracias", "ok", "vale", "👍", "👎"]
    user_text_lower = user_text.lower() # Lo ponemos en minúsculas ahora

    # Verificamos si es un feedback o un mensaje de sistema
    if user_text_lower in ["�� útil", "👎 no útil", "❓ nueva pregunta"]:
        if context.user_data.get('last_assistant_message'):
            last_message = context.user_data['last_assistant_message']
            if user_text_lower == "👍 útil":
                add_feedback(user_id, last_message, 'positive')
                await update.message.reply_text("¡Gracias por tu feedback positivo!")
            elif user_text_lower == "👎 no útil":
                add_feedback(user_id, last_message, 'negative')
                await update.message.reply_text("Gracias por tu feedback. Lo tendremos en cuenta para mejorar.")
            # Limpiamos el mensaje guardado
            del context.user_data['last_assistant_message']
        else:
             await update.message.reply_text("Gracias por tu feedback.")
        return # No procesamos estos mensajes con OpenAI

    # Si es un mensaje de cortesía, no procesamos ni pedimos feedback
    if user_text_lower in cortesia:
        await update.message.reply_text("👍") # Respuesta simple para cortesía
        return

    # --- Procesamiento con OpenAI ---
    # Incrementar contador de mensajes ANTES de llamar a OpenAI
    update_user_usage(user_id, message_increment=1)

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
            model="gpt-4-turbo-preview",
            temperature=0.7,
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
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        
        # Obtener la última respuesta del asistente
        assistant_response = messages.data[0].content[0].text.value

         # --- Guardar el último mensaje para feedback --- <-- NUEVO
        context.user_data['last_assistant_message'] = assistant_response
         # --------------------------------------------

    except Exception as e:
        logging.error(f"Error processing message: {str(e)}")
        assistant_response = f"Lo siento, hubo un error al procesar tu mensaje: {str(e)}"
        # Limpiar el hilo si hay un error
        if user_id in user_threads:
            del user_threads[user_id]
        # No guardamos este mensaje de error para feedback
        if 'last_assistant_message' in context.user_data:
            del context.user_data['last_assistant_message']

    # Respondemos al usuario con el texto del asistente
    await update.message.reply_text(assistant_response)
    
    # Solo añadimos botones de feedback si no hubo error y no fue cortesía
    if "Lo siento, hubo un error" not in assistant_response:
        keyboard = [["👍 Útil", "👎 No útil"]] # Quitamos "Nueva pregunta"
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
    user_data = get_user(user_id)

    if not user_data:
        await update.message.reply_text("No encuentro tus datos. Por favor, usa /start primero.")
        return

    current_plan_type = user_data['plan']
    current_plan = SUBSCRIPTION_PLANS[current_plan_type]
    message_count = user_data['message_count']
    # token_count = user_data['token_count'] # Podrías añadir esto si lo usas

    message = f"📊 Tu plan actual: {current_plan['name']}\n"
    message += f"📝 Mensajes usados hoy: {message_count}/{current_plan['daily_messages']}\n"
    # message += f"🔢 Tokens usados hoy: {token_count}/{current_plan['tokens_per_day']}\n" # Descomentar si usas tokens

    if current_plan_type != "FREE" and user_data['expiry_date']:
        expiry = datetime.fromisoformat(user_data['expiry_date'])
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
    
    if current_plan_type == "FREE":
        message += "\n🌟 Usa /upgrade para mejorar tu plan"
    
    await update.message.reply_text(message)

def main():
    logging.info("Starting bot...")
    verify_env_variables()
    
    try:
        # Inicializar SQLite <-- NUEVO
        init_db()

        application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            # .concurrent_updates(False) # Puedes volver a probar True si quieres concurrencia
            .concurrent_updates(True)
            .connection_pool_size(16) # Añadido para manejar concurrencia
            .connect_timeout(20.0)
            .read_timeout(20.0)
            .write_timeout(20.0)
            .build()
        )
        
        # Registramos el manejador de errores
        application.add_error_handler(error_handler)

        # Registramos los handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("faq", faq_command))
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

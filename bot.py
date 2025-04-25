import os
# import requests  # Eliminar esta línea ya que no lo usamos
import logging
import time
import sys
import sqlite3 # <-- Añadir importación
import re # <--- Añadir import
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)
from openai import OpenAI
from dotenv import load_dotenv
import httpx
from datetime import datetime, date, timedelta # <-- Añadir timedelta
import stripe # <-- Añadir import

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
DB_PATH = '/data/dpdr_bot.db' # <-- Añadido para usar el volumen persistente

# Nuevas variables de Stripe
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PRICE_ID_BASIC = os.getenv('STRIPE_PRICE_ID_BASIC')
STRIPE_PRICE_ID_PREMIUM = os.getenv('STRIPE_PRICE_ID_PREMIUM')
YOUR_DOMAIN = os.getenv('YOUR_DOMAIN', 'http://localhost:8080') # Dominio base

# Configurar la clave API de Stripe globalmente
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logging.warning("STRIPE_SECRET_KEY no encontrada. La integración con Stripe no funcionará.")

# Inicializamos el cliente de OpenAI
client = OpenAI(
    default_headers={"OpenAI-Beta": "assistants=v2"}
)

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

# --- Función Auxiliar para Limpiar Citas ---
def clean_citations(text: str) -> str:
    """Elimina patrones de citas de OpenAI (ej: 【...†...】 o [数字:数字†...]) del texto."""
    pattern1 = r'\s*【.*?†.*?】'
    pattern2 = r'\s*\[\d+:\d+†.*?\]'
    cleaned_text = re.sub(pattern1, '', text)
    cleaned_text = re.sub(pattern2, '', cleaned_text)
    return cleaned_text.strip()

# --- Funciones de Base de Datos SQLite --- <-- NUEVO
def init_db():
    """Inicializa la base de datos SQLite si no existe y añade columnas si faltan."""
    conn = None
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Crear tabla de usuarios si no existe
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                plan TEXT DEFAULT 'FREE',
                expiry_date TEXT,
                message_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                last_reset_date TEXT,
                thread_id TEXT DEFAULT NULL
            )
        """)
        # Intentar añadir la columna thread_id si no existe (para compatibilidad)
        try:
            c.execute("ALTER TABLE users ADD COLUMN thread_id TEXT DEFAULT NULL")
            logging.info("Columna 'thread_id' añadida a la tabla 'users'.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise e
            else:
                logging.info("Columna 'thread_id' ya existía.")

        # Crear tabla de feedback si no existe
        c.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                rating TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()
        logging.info("✅ Base de datos SQLite inicializada/verificada.")
    except sqlite3.Error as e:
        logging.error(f"❌ Error inicializando SQLite: {str(e)}")
    finally:
        if conn:
            conn.close()

def add_user(user_id: int):
    """Añade un usuario nuevo a la base de datos si no existe."""
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
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
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row # Devuelve filas como diccionarios
        c = conn.cursor()
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
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
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

def update_user_plan(user_id: int, plan: str, expiry_date_iso: str | None):
    """Actualiza el plan y la fecha de expiración de un usuario."""
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET plan = ?, expiry_date = ? WHERE user_id = ?",
                  (plan.upper(), expiry_date_iso, user_id))
        conn.commit()
        logging.info(f"Plan actualizado para {user_id}: {plan.upper()}, Expiración: {expiry_date_iso}")
        return True
    except sqlite3.Error as e:
        logging.error(f"Error actualizando plan para {user_id}: {e}")
        return False
    finally:
        conn.close()

def add_feedback(user_id: int, message: str, rating: str):
    """Guarda el feedback del usuario en la base de datos."""
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO feedback (user_id, message, rating, timestamp) VALUES (?, ?, ?, ?)",
                  (user_id, message, rating, timestamp))
        conn.commit()
        logging.info(f"Feedback guardado para usuario {user_id}: {rating}")
    except sqlite3.Error as e:
        logging.error(f"Error guardando feedback para usuario {user_id}: {e}")
    finally:
        conn.close()

def get_recent_feedback(limit: int = 5):
    """Obtiene las últimas 'limit' entradas de feedback de la base de datos."""
    conn = None # Inicializar conn
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row # Devuelve filas como diccionarios
        c = conn.cursor()
        c.execute("SELECT * FROM feedback ORDER BY timestamp DESC LIMIT ?", (limit,))
        feedback_data = c.fetchall()
        return feedback_data # Devuelve una lista de filas (o lista vacía)
    except sqlite3.Error as e:
        logging.error(f"Error obteniendo feedback: {e}")
        return [] # Devuelve lista vacía en caso de error
    finally:
        conn.close()

def get_all_users(plan_filter: str | None = None):
    """Obtiene todos los usuarios, opcionalmente filtrados por plan."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT user_id, plan FROM users ORDER BY user_id"
        params = []
        if plan_filter:
            query = "SELECT user_id, plan FROM users WHERE plan = ? ORDER BY user_id"
            params.append(plan_filter.upper())
            
        c.execute(query, params)
        users = c.fetchall()
        return users # Lista de usuarios o lista vacía
    except sqlite3.Error as e:
        logging.error(f"Error obteniendo todos los usuarios: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_user_thread_id(user_id: int, thread_id: str | None):
    """Actualiza o borra el thread_id de OpenAI para un usuario."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET thread_id = ? WHERE user_id = ?", (thread_id, user_id))
        conn.commit()
        logging.info(f"Thread ID actualizado para {user_id}: {'Borrado' if thread_id is None else thread_id}")
        return True
    except sqlite3.Error as e:
        logging.error(f"Error actualizando thread_id para {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

# --- Fin Funciones de Base de Datos ---

# --- Constantes para Estados de Conversación ---
ASK_EXPLAIN_TARGET = range(1)

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
    """Se ejecuta cuando el usuario usa /start y envía un saludo bilingüe."""
    user_id = update.effective_user.id
    add_user(user_id) # <-- Añadir usuario a la BD al iniciar

    welcome_message = (
        "¡Hola! Soy un asistente especializado en los síntomas de la ansiedad DPDR (despersonalización y desrealización). "
        "Puedo ayudarte con información y consejos basados en guías y recursos especializados.\n\n"
        "📌 **Comandos disponibles:**\n"
        "/faq - Ver categorías principales\n"
        "/help - Ver todos los comandos\n"
        "/plan - Ver tu plan actual y límites\n"
        "/reset - Reiniciar conversación\n\n"
        "¿En qué puedo ayudarte?\n"
        "---\n"
        "Hi! I'm an assistant specializing in the symptoms of DPDR anxiety (depersonalization and derealization). "
        "I can help you with information and advice based on specialized guides and resources.\n\n"
        "📌 **Available commands:**\n"
        "/faq - View main categories\n"
        "/help - View all commands\n"
        "/plan - View your current plan and limits\n"
        "/reset - Restart conversation\n\n"
        "How can I help you?"
    )
    await update.message.reply_text(welcome_message)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ Maneja mensajes de texto, incluyendo las opciones simples del FAQ """
    if update.message and update.message.text and update.message.text.startswith('/'):
        return # Ignorar comandos explícitamente

    user_id = update.effective_user.id
    user_text = update.message.text

    # --- Lógica de Límites (sin cambios) ---
    user_data = get_user(user_id)
    if not user_data:
        add_user(user_id)
        user_data = get_user(user_id)
        if not user_data:
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

    # --- Procesamiento ---
    is_feedback_message = False
    if user_text.lower() in ["👍 útil", "👎 no útil"]:
        is_feedback_message = True
        if context.user_data.get('last_assistant_message'):
            last_message = context.user_data['last_assistant_message']
            rating = 'positive' if user_text.lower() == "👍 útil" else 'negative'
            add_feedback(user_id, last_message, rating)
            feedback_reply = "¡Gracias por tu feedback positivo!" if rating == 'positive' else "Gracias por tu feedback. Lo tendremos en cuenta para mejorar."
            await update.message.reply_text(feedback_reply)
            del context.user_data['last_assistant_message']
        else:
             await update.message.reply_text("Gracias por tu feedback.")
        return

    if user_text.lower() in ["de nada", "gracias", "ok", "vale", "👍", "👎"]:
        await update.message.reply_text("👍")
        return

    # --- Preparar llamada a OpenAI ---
    update_user_usage(user_id, message_increment=1)

    instruction_to_use = None
    message_content = user_text

    # --- Manejo específico para opciones simples de FAQ ---
    if user_text == "Entender DPDR":
        instruction_to_use = (
            "Proporciona una explicación clara y tranquilizadora sobre qué es el DPDR, "
            "dirigida a alguien que lo está experimentando. Explica que es una respuesta de protección del cerebro "
            "ante el estrés o la ansiedad intensa (mecanismo primitivo de 'congelación' o disociación), "
            "enfatizando que no es peligroso, ni significa volverse loco, y es temporal. "
            "Usa un tono empático y normalizador."
        )
        message_content = "¿Qué es el DPDR explicado de forma tranquilizadora para quien lo sufre?"

    elif user_text == "Ansiedad general":
        instruction_to_use = (
            "Proporciona una introducción clara y tranquilizadora sobre qué es la ansiedad generalizada (TAG). "
            "Explica que es más que una preocupación normal, describiendo sus síntomas comunes (preocupación excesiva, "
            "inquietud, fatiga, tensión muscular, problemas de sueño). Menciona que, aunque puede ser debilitante, "
            "es tratable. Explica brevemente que puede surgir de una combinación de factores (genética, química cerebral, "
            "experiencias vitales). Usa un tono empático e informativo."
        )
        message_content = "¿Qué es la ansiedad general explicada de forma tranquilizadora?"

    # --- Construir Instrucción Final ---
    if instruction_to_use:
        final_instructions = instruction_to_use + (
            " Responde en el mismo idioma que el usuario. "
            "Es **absolutamente prohibido** incluir cualquier tipo de anotación, cita o referencia a archivos fuente "
            "(ej: 【...†source】, [...]) en la respuesta. La respuesta debe ser texto limpio sin esas anotaciones."
        )
    else:
        base_instructions = (
            "Actúa como un asistente empático y conocedor, especializado en DPDR pero también capaz de "
            "ofrecer apoyo e información sobre la ansiedad en general. Basa tus respuestas en tu conocimiento, "
            "especialmente en DPDR. Proporciona respuestas claras y de apoyo."
        )
        final_instructions = base_instructions + (
            " Responde en el mismo idioma que el usuario. "
            "Es **absolutamente prohibido** incluir cualquier tipo de anotación, cita o referencia a archivos fuente "
            "(ej: 【...†source】, [...]) en la respuesta. La respuesta debe ser texto limpio sin esas anotaciones."
        )

    # --- Llamada a OpenAI (con persistencia de hilos) ---
    assistant_response = ""
    try:
        user_data = get_user(user_id) # Reobtener por si thread_id cambió
        current_thread_id = user_data.get('thread_id') if user_data and 'thread_id' in user_data else None

        if not current_thread_id:
            logging.info(f"DB: No thread_id found for user {user_id}. Creating new one.")
            thread = client.beta.threads.create()
            current_thread_id = thread.id
            logging.info(f"API: New thread created: {current_thread_id}")
            update_user_thread_id(user_id, current_thread_id)
            logging.info(f"DB: Saved new thread_id {current_thread_id} for user {user_id}.")
        else:
            logging.info(f"DB: Found existing thread_id for user {user_id}: {current_thread_id}")

        logging.info(f"Using thread_id: {current_thread_id} for user {user_id}")
        logging.info(f"Final Instructions: {final_instructions}")

        message = client.beta.threads.messages.create(
            thread_id=current_thread_id,
            role="user",
            content=message_content
        )
        logging.info(f"Message added to thread {current_thread_id}")

        run = client.beta.threads.runs.create(
            thread_id=current_thread_id,
            assistant_id=ASSISTANT_ID,
            model="gpt-4o",
            temperature=0.7,
            instructions=final_instructions
        )
        logging.info(f"Run {run.id} created for thread {current_thread_id}")

        await update.message.reply_text("Procesando tu pregunta, por favor espera...")

        start_time = time.time()
        completed = False
        while not completed and (time.time() - start_time) < 300:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=current_thread_id,
                run_id=run.id
            )
            if run_status.status == 'completed':
                completed = True
                break
            elif run_status.status == 'failed':
                raise Exception(f"Error del asistente: {run_status.last_error}")
            time.sleep(2)

        if not completed:
            raise TimeoutError("El asistente tardó demasiado en responder")

        messages = client.beta.threads.messages.list(thread_id=current_thread_id)
        assistant_response = messages.data[0].content[0].text.value
        context.user_data['last_assistant_message'] = assistant_response

        # <<< --- LIMPIAR CITAS ANTES DE ENVIAR --- >>>
        cleaned_response = clean_citations(assistant_response)
        # <<< ------------------------------------ >>>

    except Exception as e:
        logging.error(f"Error processing message for user {user_id}: {str(e)}")
        cleaned_response = f"Lo siento, hubo un error al procesar tu mensaje: {str(e)}"
        if 'last_assistant_message' in context.user_data:
            del context.user_data['last_assistant_message']

    # --- Respuesta y Feedback ---
    await update.message.reply_text(cleaned_response)
    
    if not is_feedback_message and "Lo siento, hubo un error" not in cleaned_response:
        keyboard = [["👍 Útil", "👎 No útil"]]
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
    """Reinicia la conversación del usuario borrando su thread_id."""
    user_id = update.effective_user.id
    update_user_thread_id(user_id, None) # Borrar de la BD
    await update.message.reply_text(
        "He reiniciado tu conversación. La próxima vez que me escribas, empezaré un nuevo hilo."
    )

async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra categorías de preguntas frecuentes actualizadas."""
    keyboard = [
        ["Entender DPDR", "Ansiedad general"],
        ["Síntomas", "Ejercicios"],
        ["Explicar a Otros", "Recursos"] # Renombrado y añadida Ansiedad
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True) # Hacer resize
    await update.message.reply_text(
        "Selecciona un área de interés:\n\n"
        "🧠 **Entender DPDR:** Una explicación tranquilizadora sobre qué es y por qué ocurre.\n"
        "🌀 **Ansiedad general:** Información sobre la ansiedad, sus mecanismos y cómo se manifiesta.\n"
        "❤️ **Explicar a Otros:** Ayuda para describir tu experiencia (DPDR o ansiedad) a familiares y amigos.\n"
        "🩺 **Síntomas:** Un repaso a los síntomas comunes y qué pueden indicar.\n"
        "🧘 **Ejercicios:** Técnicas y ejercicios prácticos para manejar DPDR y ansiedad.\n"
        "📚 **Recursos:** Enlaces, libros y otros materiales de apoyo.",
        reply_markup=reply_markup
    )

async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra opciones para actualizar el plan con botones inline."""
    if not STRIPE_PRICE_ID_BASIC or not STRIPE_PRICE_ID_PREMIUM:
        await update.message.reply_text("Lo siento, la opción de mejora de plan no está configurada correctamente.")
        logging.error("IDs de precios de Stripe no configurados en variables de entorno.")
        return
        
    keyboard = [
        [
            InlineKeyboardButton(f"💎 Plan Basic - {SUBSCRIPTION_PLANS['BASIC']['price']}€/mes", callback_data=f"upgrade_basic_{STRIPE_PRICE_ID_BASIC}"),
        ],
        [
            InlineKeyboardButton(f"👑 Plan Premium - {SUBSCRIPTION_PLANS['PREMIUM']['price']}€/mes", callback_data=f"upgrade_premium_{STRIPE_PRICE_ID_PREMIUM}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        "Selecciona el plan al que quieres actualizar:\n\n"
        f"💎 **Plan Basic ({SUBSCRIPTION_PLANS['BASIC']['price']}€/mes):**\n"
        f"- {SUBSCRIPTION_PLANS['BASIC']['daily_messages']} mensajes/día\n\n"
        f"👑 **Plan Premium ({SUBSCRIPTION_PLANS['PREMIUM']['price']}€/mes):**\n"
        f"- {SUBSCRIPTION_PLANS['PREMIUM']['daily_messages']} mensajes/día\n\n"
        "*Serás redirigido a Stripe para completar el pago seguro.*"
    )
    await update.message.reply_text(message_text, reply_markup=reply_markup)

async def create_stripe_checkout_session(price_id: str, user_id: int) -> str | None:
    """Crea una sesión de Checkout en Stripe y devuelve la URL."""
    if not stripe.api_key:
        logging.error("Intento de crear sesión de Stripe sin API key configurada.")
        return None
        
    try:
        # Verificar que YOUR_DOMAIN no es el valor por defecto si no estamos en debug local
        # Esto es una heurística, idealmente se controlaría con una variable de entorno diferente
        success_url_base = YOUR_DOMAIN
        cancel_url_base = YOUR_DOMAIN
        # Podríamos añadir lógica para usar una URL pública real si está disponible
        
        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=f'{success_url_base}/stripe-success?session_id={{CHECKOUT_SESSION_ID}}', 
            cancel_url=f'{cancel_url_base}/stripe-cancel',
            client_reference_id=str(user_id),
            metadata={'telegram_user_id': str(user_id)} # Incluir en metadata también
        )
        logging.info(f"Sesión de Stripe Checkout creada para user {user_id}, price {price_id}: {checkout_session.id}")
        return checkout_session.url
    except Exception as e:
        logging.error(f"Error creando sesión de Stripe Checkout para user {user_id}: {e}")
        return None

async def upgrade_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los clics en los botones de actualización de plan."""
    query = update.callback_query
    await query.answer() # Obligatorio

    callback_data = query.data
    user_id = query.from_user.id

    logging.info(f"Recibido callback_data: {callback_data} de user {user_id}")

    try:
        parts = callback_data.split('_')
        if len(parts) < 3 or not parts[0] == 'upgrade':
            raise ValueError("Formato de callback_data incorrecto")
        plan_type = parts[1]
        # Corregir: Usar '_' para unir las partes del ID
        price_id = '_'.join(parts[2:]) # <-- CORRECCIÓN FINAL
    except (IndexError, ValueError) as e:
        logging.error(f"Error parseando callback_data '{callback_data}': {e}")
        await query.edit_message_text(text="Error procesando la selección. Inténtalo de nuevo.")
        return

    # <<< --- AÑADIR ESTE LOG --- >>>
    logging.info(f"Extracted Price ID from callback: '{price_id}' for plan {plan_type}")
    # <<< ----------------------- >>>

    # Editar mensaje para indicar progreso
    try:
         await query.edit_message_text(text=f"⏳ Creando enlace de pago seguro para el Plan {plan_type.capitalize()}...")
    except Exception as e:
        # Ignorar error si el mensaje no se puede editar (ej: demasiado viejo)
        logging.warning(f"No se pudo editar mensaje para callback {query.id}: {e}")

    checkout_url = await create_stripe_checkout_session(price_id, user_id)

    if checkout_url:
        keyboard = [[InlineKeyboardButton("➡️ Ir a Pagar a Stripe", url=checkout_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Intentar editar de nuevo o enviar nuevo mensaje si falla
        try:
            await query.edit_message_text(
                text=f"¡Listo! Haz clic en el botón para completar tu suscripción al Plan {plan_type.capitalize()} en Stripe:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.warning(f"No se pudo editar mensaje final para callback {query.id}, enviando nuevo: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"¡Listo! Haz clic en el botón para completar tu suscripción al Plan {plan_type.capitalize()} en Stripe:",
                reply_markup=reply_markup
            )
    else:
        try:
            await query.edit_message_text(text="❌ Lo siento, hubo un error al crear el enlace de pago. Por favor, intenta de nuevo más tarde.")
        except Exception as e:
             logging.warning(f"No se pudo editar mensaje de error para callback {query.id}, enviando nuevo: {e}")
             await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Lo siento, hubo un error al crear el enlace de pago. Por favor, intenta de nuevo más tarde."
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

# --- Funciones de Admin ---
async def admin_user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Muestra información de un usuario específico."""
    admin_id = update.effective_user.id

    # 1. Verificar si es admin
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    # 2. Obtener el user_id objetivo del comando
    try:
        target_user_id_str = context.args[0]
        target_user_id = int(target_user_id_str)
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Uso: /user_info <user_id>")
        return

    # 3. Obtener datos del usuario
    user_data = get_user(target_user_id)

    if not user_data:
        await update.message.reply_text(f"❌ No se encontró usuario con ID: {target_user_id}")
        return

    # 4. Formatear y enviar respuesta
    current_plan_type = user_data['plan']
    current_plan = SUBSCRIPTION_PLANS[current_plan_type]
    message_count = user_data['message_count']
    last_reset = user_data['last_reset_date']

    message = f"ℹ️ **Información del Usuario: {target_user_id}**\n\n"
    message += f"👤 **ID:** `{target_user_id}`\n"
    message += f"🏷️ **Plan:** {current_plan['name']} (`{current_plan_type}`)\n"
    message += f"✉️ **Mensajes Hoy:** {message_count}/{current_plan['daily_messages']}\n"
    # Añadir tokens si se implementa
    # token_count = user_data['token_count']
    # message += f"🔢 **Tokens Hoy:** {token_count}/{current_plan['tokens_per_day']}\n"
    message += f"🔄 **Último Reseteo:** {last_reset}\n"

    if user_data['expiry_date']:
        expiry = datetime.fromisoformat(user_data['expiry_date'])
        message += f"⏳ **Expiración Plan:** {expiry.strftime('%d/%m/%Y')}\n"
    else:
        message += "⏳ **Expiración Plan:** N/A (Plan Gratuito)\n"

    await update.message.reply_text(message, parse_mode='Markdown')

async def admin_set_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Establece el plan y opcionalmente la duración para un usuario."""
    admin_id = update.effective_user.id

    # 1. Verificar si es admin
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    # 2. Parsear y validar argumentos
    if len(context.args) < 2 or len(context.args) > 3:
        await update.message.reply_text("⚠️ Uso: /set_plan <user_id> <PLAN> [dias]")
        return

    try:
        target_user_id = int(context.args[0])
        target_plan_name = context.args[1].upper()
        duration_days = None
        if len(context.args) == 3:
            duration_days = int(context.args[2])
            if duration_days <= 0:
                raise ValueError("Los días deben ser un número positivo.")

        if target_plan_name not in SUBSCRIPTION_PLANS:
            raise ValueError(f"Plan inválido. Opciones: {', '.join(SUBSCRIPTION_PLANS.keys())}")

    except ValueError as e:
        await update.message.reply_text(f"❌ Error en los argumentos: {e}")
        return

    # 3. Calcular fecha de expiración
    expiry_date_iso = None
    if target_plan_name != 'FREE' and duration_days is not None:
        expiry_date = date.today() + timedelta(days=duration_days)
        expiry_date_iso = expiry_date.isoformat()
    # Si se cambia a FREE (o no se dan días para un plan de pago), la expiración se limpia

    # 4. Actualizar base de datos
    success = update_user_plan(target_user_id, target_plan_name, expiry_date_iso)

    # 5. Confirmar al admin
    if success:
        expiry_msg = f" con expiración el {datetime.fromisoformat(expiry_date_iso).strftime('%d/%m/%Y')}" if expiry_date_iso else " (sin expiración definida)"
        await update.message.reply_text(f"✅ Plan actualizado para el usuario `{target_user_id}`.\nNuevo plan: **{target_plan_name}**{expiry_msg}", parse_mode='Markdown')
        # Opcional: Podrías resetear los contadores del día al cambiar de plan
        # update_user_usage(target_user_id, message_increment=-get_user(target_user_id)['message_count']) # Reset msg count
    else:
        await update.message.reply_text(f"❌ Error al actualizar el plan para el usuario `{target_user_id}` en la base de datos.")

async def admin_view_feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Muestra las últimas N entradas de feedback."""
    admin_id = update.effective_user.id

    # 1. Verificar si es admin
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    # 2. Obtener cantidad (opcional)
    limit = 5 # Valor por defecto
    if context.args and len(context.args) == 1:
        try:
            limit = int(context.args[0])
            if limit <= 0:
                raise ValueError("La cantidad debe ser positiva.")
            if limit > 50: # Prevenir pedir demasiados
                 limit = 50
                 await update.message.reply_text("⚠️ Mostrando un máximo de 50 entradas.")
        except ValueError:
            await update.message.reply_text("⚠️ Uso: /view_feedback [cantidad] (la cantidad debe ser un número positivo)")
            return
    elif len(context.args) > 1:
         await update.message.reply_text("⚠️ Uso: /view_feedback [cantidad]")
         return

    # 3. Obtener feedback de la BD
    feedback_entries = get_recent_feedback(limit)

    if not feedback_entries:
        await update.message.reply_text("ℹ️ No hay entradas de feedback todavía.")
        return

    # 4. Formatear y enviar respuesta
    message = f"💬 **Últimas {len(feedback_entries)} entradas de Feedback:**\n\n"
    for entry in feedback_entries:
        timestamp_dt = datetime.fromisoformat(entry['timestamp'])
        formatted_ts = timestamp_dt.strftime('%Y-%m-%d %H:%M')
        rating_emoji = "👍" if entry['rating'] == 'positive' else "👎"
        message += f"* **Usuario:** `{entry['user_id']}` ({rating_emoji} {entry['rating']})\n"
        message += f"* **Fecha:** {formatted_ts}\n"
        # Escapamos caracteres markdown en el mensaje de feedback (usando doble \\)
        safe_message = entry['message'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
        message += f"* **Mensaje Asistente:** \n```\n{safe_message}\n```\n"
        message += "---\n"

    # Enviar mensajes largos en partes si es necesario
    if len(message) > 4096:
        for i in range(0, len(message), 4096):
            await update.message.reply_text(message[i:i+4096], parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

async def admin_list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Lista todos los usuarios, opcionalmente filtrados por plan."""
    admin_id = update.effective_user.id

    # 1. Verificar si es admin
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    # 2. Obtener filtro de plan (opcional)
    plan_filter = None
    if context.args:
        if len(context.args) == 1:
            plan_filter_arg = context.args[0].upper()
            if plan_filter_arg in SUBSCRIPTION_PLANS:
                plan_filter = plan_filter_arg
            else:
                await update.message.reply_text(f"⚠️ Plan inválido: {context.args[0]}. Opciones: {', '.join(SUBSCRIPTION_PLANS.keys())}")
                return
        else:
            await update.message.reply_text("⚠️ Uso: /list_users [PLAN]")
            return
            
    # 3. Obtener usuarios de la BD
    users = get_all_users(plan_filter)

    if not users:
        filter_msg = f" con plan {plan_filter}" if plan_filter else ""
        await update.message.reply_text(f"ℹ️ No se encontraron usuarios{filter_msg}.")
        return

    # 4. Formatear y enviar respuesta (con paginación simple)
    header = f"👥 **Lista de Usuarios ({len(users)} total{'es' if len(users) != 1 else ''})**"
    if plan_filter:
        header += f" - Plan: {plan_filter}"
    header += "\n---\n"
    
    message_part = header
    line_count = 0
    max_lines_per_message = 50 # Aproximado para no superar límite de Telegram

    for user in users:
        line = f"`{user['user_id']}` - {user['plan']}\n"
        if line_count >= max_lines_per_message:
            await update.message.reply_text(message_part, parse_mode='Markdown')
            message_part = header # Reiniciar para el siguiente mensaje
            line_count = 0
            
        message_part += line
        line_count += 1

    # Enviar la última parte (o la única si es corta)
    if message_part != header: # Asegurar que hay contenido para enviar
         await update.message.reply_text(message_part, parse_mode='Markdown')

# --- Funciones para la Conversación "Explicar a Otros" ---
async def explain_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Punto de entrada para la conversación 'Explicar a Otros'."""
    # Podríamos verificar límites aquí también si queremos que cuente como mensaje
    # user_id = update.effective_user.id
    # update_user_usage(user_id, message_increment=1)
    await update.message.reply_text(
        "Entendido. A veces es difícil poner en palabras lo que sentimos. 😊\n\n"
        "¿Sobre qué te gustaría que prepare una explicación sencilla para tus familiares o amigos?\n"
        "Por ejemplo: 'DPDR', 'ansiedad', 'sentirme irreal', 'ataques de pánico'..."
    )
    return ASK_EXPLAIN_TARGET

async def explain_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe el tema que el usuario quiere explicar y genera la respuesta."""
    user_topic = update.message.text
    user_id = update.effective_user.id
    
    # Incrementar contador aquí, ya que es una interacción significativa
    update_user_usage(user_id, message_increment=1) 
    # (Habría que verificar límites aquí si no se hizo en explain_entry)

    await update.message.reply_text("Vale, preparando una explicación sobre '{}'... ".format(user_topic))

    explain_instruction = (
        f"Actúa como alguien que ayuda a explicar condiciones de salud mental a familiares y amigos de forma muy sencilla y empática. "
        f"El usuario quiere explicar '{user_topic}'. Genera un texto corto (máximo 3-4 párrafos) que el usuario pueda compartir. "
        f"Debe ser fácil de entender para alguien sin conocimientos previos, usando analogías si es posible, validando la experiencia "
        f"y enfocándose en cómo pueden apoyar. Evita jerga técnica compleja. Si el tema es vago, intenta dar una explicación general útil."
    )
    final_instructions = explain_instruction + (
        " Responde en el mismo idioma que el usuario. "
        "Es **absolutamente prohibido** incluir cualquier tipo de anotación, cita o referencia a archivos fuente "
        "(ej: 【...†source】, [...]) en la respuesta. La respuesta debe ser texto limpio sin esas anotaciones."
    )

    assistant_response = ""
    try:
        user_data = get_user(user_id)
        current_thread_id = user_data.get('thread_id') if user_data and 'thread_id' in user_data else None
        if not current_thread_id:
             logging.info(f"DB: No thread_id found for user {user_id} in explain_conv. Creating new one.")
             thread = client.beta.threads.create()
             current_thread_id = thread.id
             update_user_thread_id(user_id, current_thread_id)
             logging.info(f"DB: Saved new thread_id {current_thread_id} for user {user_id}.")
        else:
             logging.info(f"DB: Found existing thread_id for user {user_id}: {current_thread_id}")

        logging.info(f"Using thread_id: {current_thread_id} for user {user_id} (Explain Conv)")
        logging.info(f"Final Instructions (Explain Conv): {final_instructions}")

        message = client.beta.threads.messages.create(
            thread_id=current_thread_id,
            role="user",
            content=f"Generar explicación para familiares/amigos sobre: {user_topic}" # Usar un prompt interno
        )

        run = client.beta.threads.runs.create(
            thread_id=current_thread_id, assistant_id=ASSISTANT_ID, model="gpt-4o",
            temperature=0.7, instructions=final_instructions
        )
        
        start_time = time.time()
        completed = False
        while not completed and (time.time() - start_time) < 300:
             run_status = client.beta.threads.runs.retrieve(thread_id=current_thread_id, run_id=run.id)
             if run_status.status == 'completed': completed = True; break
             elif run_status.status == 'failed': raise Exception(f"Error del asistente: {run_status.last_error}")
             time.sleep(2)
        if not completed: raise TimeoutError("Timeout en la respuesta del asistente")
        
        messages = client.beta.threads.messages.list(thread_id=current_thread_id)
        assistant_response = messages.data[0].content[0].text.value

        # <<< --- LIMPIAR CITAS ANTES DE ENVIAR --- >>>
        cleaned_response = clean_citations(assistant_response)
        # <<< ------------------------------------ >>>

    except Exception as e:
        logging.error(f"Error processing explain_target for user {user_id}: {str(e)}")
        cleaned_response = f"Lo siento, hubo un error al generar la explicación: {str(e)}"

    await update.message.reply_text(
        "Aquí tienes una propuesta de explicación que puedes compartir o adaptar:\n\n---\n"
        f"{cleaned_response}\n---\n\n"
        "Espero que sea útil. ¿Puedo ayudarte con algo más?"
    )
    return ConversationHandler.END

async def explain_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la conversación actual."""
    await update.message.reply_text(
        "De acuerdo, cancelamos la preparación de la explicación. Puedes usar /faq cuando quieras."
    )
    return ConversationHandler.END

# --- Fin Funciones Conversación ---

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

        # --- Crear ConversationHandler para "Explicar a Otros" ---
        explain_conv_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.TEXT & filters.Regex('^Explicar a Otros$'), explain_entry)],
            states={
                ASK_EXPLAIN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, explain_target_received)],
            },
            fallbacks=[CommandHandler('cancel', explain_cancel)],
            # conversation_timeout=300 # Opcional: 5 minutos
        )
        # --- Fin ConversationHandler ---

        # Registramos los handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("faq", faq_command))
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("upgrade", upgrade_command))
        
        # Añadir PRIMERO el ConversationHandler
        application.add_handler(explain_conv_handler)

        # --- Añadir Handler para botones de Upgrade --- <--- MOVIDO AQUÍ
        application.add_handler(CallbackQueryHandler(upgrade_button_handler, pattern='^upgrade_'))
        # --------------------------------------------

        # Handler general de mensajes (al final)
        # (Debe ignorar el texto de los botones que inician conversaciones)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex('^Explicar a Otros$'), handle_message))

        # --- Añadir comandos de Admin ---
        application.add_handler(CommandHandler("user_info", admin_user_info_command))
        application.add_handler(CommandHandler("set_plan", admin_set_plan_command))
        application.add_handler(CommandHandler("view_feedback", admin_view_feedback_command))
        application.add_handler(CommandHandler("list_users", admin_list_users_command))
        # -------------------------------

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

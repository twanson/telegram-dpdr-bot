import os
# import requests  # Eliminar esta línea ya que no lo usamos
import logging
import time
import sys
import sqlite3 # <-- Añadir importación
import re # <--- Añadir import
import asyncio # <-- Añadir import
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode # <-- Importación corregida
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

# Lista de IDs de administradores
ADMIN_IDS = [
    23684095  # Admin principal
]

# Palabras clave para usar GPT-4o por seguridad (Versión Refinada)
CRITICAL_KEYWORDS = [
    # Palabras/Frases de Alto Riesgo (Español)
    "matarme", "suicidio", "suicida", "suicidarme", 
    "hacerme daño", "autolesión", "autolesionarme", "autolesion",
    "acabar con todo", "no quiero vivir", "desaparecer",
    "no puedo más", # (Umbral alto de desesperación)
    # "cortarme", # (Considerar si añadir o no, puede ser específico de autolesión) 

    # Palabras/Frases de Alto Riesgo (Inglés - Básico)
    "kill myself", "suicide", "suicidal", 
    "harm myself", "self-harm", "self harm", 
    "end it all", "don\'t want to live", "disappear", # Asegurar que el apóstrofo está escapado para Git/Shell si es necesario, pero no en la lista Python.
    "can\'t take it anymore" # Igual aquí.
]

# Variable global para activar/desactivar la comprobación de palabras clave
CHECK_CRITICAL_KEYWORDS = False # Poner a True para activar la comprobación

# --- Instrucciones Base para OpenAI --- 
BASE_INSTRUCTIONS = (
    "Actúa como un asistente empático y conocedor, especializado en DPDR pero también capaz de "
    "ofrecer apoyo e información sobre la ansiedad en general. Basa tus respuestas en tu conocimiento, "
    "especialmente en DPDR. Proporciona respuestas claras y de apoyo."
)
NO_CITATION_INSTRUCTION = (
    " Es **absolutamente prohibido** incluir cualquier tipo de anotación, cita o referencia a archivos fuente "
    "(ej: 【...†source】, [...]) en la respuesta. La respuesta debe ser texto limpio sin esas anotaciones."
)
# -------------------------------------

# --- Textos para Internacionalización (i18n) --- 
LOCALES = {
    'es': {
        # FAQ Buttons
        'faq_understand_dpdr': "Entender DPDR",
        'faq_general_anxiety': "Ansiedad general",
        'faq_symptoms': "Síntomas",
        'faq_exercises': "Ejercicios",
        'faq_explain_other': "Explicar a Otros",
        'faq_resources': "Recursos",
        # FAQ Descriptions
        'faq_select_area': "Selecciona un área de interés:",
        'faq_area_understand': "🧠 **Entender DPDR:** Una explicación tranquilizadora sobre qué es y por qué ocurre.",
        'faq_area_anxiety': "🌀 **Ansiedad general:** Información sobre la ansiedad, sus mecanismos y cómo se manifiesta.",
        'faq_area_explain': "❤️ **Explicar a Otros:** Ayuda para describir tu experiencia (DPDR o ansiedad) a familiares y amigos.",
        'faq_area_symptoms': "🩺 **Síntomas:** Un repaso a los síntomas comunes y qué pueden indicar.",
        'faq_area_exercises': "🧘 **Ejercicios:** Técnicas y ejercicios prácticos para manejar DPDR y ansiedad.",
        'faq_area_resources': "📚 **Recursos:** Enlaces, libros y otros materiales de apoyo.",
        # Feedback
        'feedback_useful': "👍 Útil", 
        'feedback_not_useful': "👎 No útil", 
        'feedback_prompt': "¿Te ha resultado útil esta respuesta?",
        'feedback_thanks_positive': "¡Gracias por tu feedback positivo! 👍",
        'feedback_thanks_negative': "Gracias por tu feedback. Lo tendremos en cuenta para mejorar. 👍",
        'feedback_thanks_generic': "Gracias por tu feedback.", 
        # Comandos
        'start_welcome_1': "¡Hola! Soy un asistente especializado en los síntomas de la ansiedad DPDR (despersonalización y desrealización).",
        'start_welcome_2': "Puedo ayudarte con información y consejos basados en guías y recursos especializados.",
        'start_commands_title': "📌 **Comandos disponibles:**",
        'start_faq': "/faq - Ver categorías principales",
        'start_plan': "/plan - Ver tu plan actual y límites",
        'start_upgrade': "/upgrade - Ver o mejorar tu plan 🌟",
        'start_reset': "/reset - Reiniciar conversación",
        'start_help': "/help - Ver todos los comandos",
        'start_cta': "¿En qué puedo ayudarte?",
        'help_title': "Comandos disponibles:",
        'help_start': "/start - Inicia el bot",
        'help_faq': "/faq - Muestra categorías de ayuda principales",
        'help_plan': "/plan - Muestra tu plan de suscripción actual y límites",
        'help_upgrade': "/upgrade - Muestra las opciones para mejorar tu plan 🌟",
        'help_reset': "/reset - Reinicia tu conversación con el bot",
        'help_help': "/help - Muestra esta lista de comandos",
        'help_support': "/support - Contactar con soporte (si necesitas ayuda)",
        'help_cta': "\nTambién puedes escribirme directamente tu pregunta o seleccionar una opción de /faq.",
        'plan_title': "📊 Tu plan actual:",
        'plan_messages_today': "✉️ Mensajes usados hoy:",
        'plan_expires': "📅 Tu suscripción vence el: {expiry_date}",
        'plan_expiry_error': "Fecha inválida",
        'plan_available_title': "💡 Planes disponibles",
        'plan_free_desc': """*GRATUITO:*
- Plan básico gratuito
- {limit} mensajes/día""",
        'plan_basic_desc': """*BÁSICO:*
- Para uso regular
- {limit} mensajes/día
- Precio: {price}€/mes""",
        'plan_premium_desc': """*PREMIUM:*
- Para uso intensivo
- {limit} mensajes/día
- Precio: {price}€/mes""",
        'plan_upgrade_cta_free': "🌟 Usa /upgrade para mejorar tu plan y obtener más mensajes diarios.",
        'plan_upgrade_cta_paid': "🌟 Puedes usar /upgrade si deseas cambiar tu plan.",
        'limit_reached_1': "Has alcanzado tu límite diario de mensajes. 🚫",
        'limit_reached_2': "Tu plan '**{plan_name}**' permite {limit} mensajes al día.",
        'limit_reached_cta': "🌟 **¡Mejora tu plan con /upgrade para obtener más mensajes diarios y seguir conversando!**",
        # Upgrade/Stripe
        'upgrade_generating_link': "Generando enlace de pago seguro...",
        'upgrade_payment_link_message': "Haz clic aquí para completar tu suscripción:",
        'error_price_id_not_found': "Error: No se encontró el ID de precio para ese plan.",
        'error_stripe_session': "Lo siento, hubo un error al generar el enlace de pago. Por favor, inténtalo de nuevo más tarde.",
        'error_processing_selection': "Error procesando la selección. Inténtalo de nuevo.",
        # Explain Conversation
        'explain_entry_prompt': "Claro, puedo ayudarte con eso. ¿Sobre qué tema específico (DPDR, ansiedad, un síntoma concreto, etc.) te gustaría que preparara una explicación sencilla para compartir?",
        'explain_cancel_instruction': "(Puedes escribir /cancel para detener esto en cualquier momento)",
        'explain_wait': "Vale, preparando una explicación sobre '{topic}'... Dame un momento.",
        'explain_response_header': "Aquí tienes una propuesta de explicación que puedes compartir o adaptar:",
        'explain_response_footer': "Espero que sea útil. ¿Puedo ayudarte con algo más?",
        'explain_cancel_confirmation': "De acuerdo, cancelamos la preparación de la explicación. Puedes usar /faq cuando quieras.",
        # Errores Genéricos
        'error_generic': "Lo siento, hubo un error al procesar tu mensaje: {error}",
        'error_no_user_data': "No encuentro tus datos. Por favor, usa /start primero.",
        'reset_confirmation': "He reiniciado tu conversación. La próxima vez que me escribas, empezaré un nuevo hilo.",
        # Support Conversation
        'support_prompt': "Por favor, describe brevemente tu consulta o problema para el equipo de soporte:",
        'support_cancel_instruction': "(Escribe /cancel si cambias de opinión)",
        'support_confirmation': "Gracias. Tu consulta ha sido enviada al equipo de soporte. Te contactarán si es necesario.",
        'support_cancel_confirmation': "De acuerdo, se canceló la solicitud de soporte.",
        'error_request_in_progress': "Estoy procesando tu solicitud anterior. Por favor, espera un momento antes de enviar una nueva.",
        'error_stripe_specific': "Error de pago: {error}",
        # Upgrade Command Text
        'upgrade_title': "Selecciona el plan al que quieres actualizar:",
        'upgrade_basic_desc': "💎 **Plan Basic ({price}€/mes):**\n- {limit} mensajes/día",
        'upgrade_premium_desc': "👑 **Plan Premium ({price}€/mes):**\n- {limit} mensajes/día",
        'upgrade_footer': "*Serás redirigido a Stripe para completar el pago seguro.*",
        'error_stripe_ids_missing': "Lo siento, la opción de mejora de plan no está configurada correctamente.",
        # Explain Conversation
        'processing_request': "🧠 Procesando tu solicitud... Por favor, espera un momento.", # <-- Añadido
        'consulting_knowledge_base': "Consultando la base de conocimiento... 🧠 Por favor, espera unos momentos mientras preparo tu respuesta.", # <-- Añadido
    },
    'en': {
        # FAQ Buttons
        'faq_understand_dpdr': "Understand DPDR",
        'faq_general_anxiety': "General Anxiety",
        'faq_symptoms': "Symptoms",
        'faq_exercises': "Exercises",
        'faq_explain_other': "Explain to Others",
        'faq_resources': "Resources",
        # FAQ Descriptions
        'faq_select_area': "Select an area of interest:",
        'faq_area_understand': "🧠 **Understand DPDR:** A reassuring explanation of what it is and why it happens.",
        'faq_area_anxiety': "🌀 **General Anxiety:** Information about anxiety, its mechanisms, and how it manifests.",
        'faq_area_explain': "❤️ **Explain to Others:** Help to describe your experience (DPDR or anxiety) to family and friends.",
        'faq_area_symptoms': "🩺 **Symptoms:** A review of common symptoms and what they might indicate.",
        'faq_area_exercises': "🧘 **Exercises:** Practical techniques and exercises to manage DPDR and anxiety.",
        'faq_area_resources': "📚 **Resources:** Links, books, and other support materials.",
        # Feedback
        'feedback_useful': "👍 Useful",
        'feedback_not_useful': "👎 Not Useful",
        'feedback_prompt': "Was this answer helpful to you?",
        'feedback_thanks_positive': "Thanks for your positive feedback! 👍",
        'feedback_thanks_negative': "Thanks for your feedback. We'll take it into account to improve. 👍",
        'feedback_thanks_generic': "Thanks for your feedback.",
        # Commands
        'start_welcome_1': "Hi! I'm an assistant specializing in the symptoms of DPDR anxiety (depersonalization and derealization).",
        'start_welcome_2': "I can help you with information and advice based on specialized guides and resources.",
        'start_commands_title': "📌 **Available commands:**",
        'start_faq': "/faq - View main categories",
        'start_plan': "/plan - View your current plan and limits",
        'start_upgrade': "/upgrade - View or upgrade your plan 🌟",
        'start_reset': "/reset - Restart conversation",
        'start_help': "/help - View all commands",
        'start_cta': "How can I help you?",
        'help_title': "Available commands:",
        'help_start': "/start - Start the bot",
        'help_faq': "/faq - Show main help categories",
        'help_plan': "/plan - Show your current subscription plan and limits",
        'help_upgrade': "/upgrade - Show options to upgrade your plan 🌟",
        'help_reset': "/reset - Restart your conversation with the bot",
        'help_help': "/help - Show this list of commands",
        'help_cta': "\nYou can also ask me your question directly or select an option from /faq.",
        'plan_title': "📊 Your current plan:",
        'plan_messages_today': "✉️ Messages used today:",
        'plan_expires': "📅 Your subscription expires on: {expiry_date}", # Added placeholder
        'plan_available_title': "💡 Available plans", # Removed colon
        'plan_free_desc': """*FREE:*
- Basic free plan
- {limit} messages/day""",
        'plan_basic_desc': """*BASIC:*
- For regular use
- {limit} messages/day
- Price: €{price}/month""",
        'plan_premium_desc': """*PREMIUM:*
- For heavy use
- {limit} messages/day
- Price: €{price}/month""",
        'plan_upgrade_cta_free': "🌟 Use /upgrade to improve your plan and get more daily messages.",
        'plan_upgrade_cta_paid': "🌟 You can use /upgrade if you wish to change your plan.",
        'limit_reached_1': "You have reached your daily message limit. 🚫",
        'limit_reached_2': "Your '**{plan_name}**' plan allows {limit} messages per day.",
        'limit_reached_cta': "🌟 **Upgrade your plan with /upgrade to get more daily messages and keep chatting!**",
        # Other texts...
        'error_generic': "Sorry, there was an error processing your message: {error}",
        'error_no_user_data': "I can't find your data. Please use /start first.",
        'reset_confirmation': "I have restarted your conversation. The next time you write to me, I will start a new thread.",
        # Support Conversation
        'support_prompt': "Please briefly describe your query or problem for the support team:",
        'support_cancel_instruction': "(Type /cancel if you change your mind)",
        'support_confirmation': "Thank you. Your query has been sent to the support team. They will contact you if necessary.",
        'support_cancel_confirmation': "Okay, the support request has been cancelled.",
        'error_request_in_progress': "I'm currently processing your previous request. Please wait a moment before sending a new one.",
        'error_processing_selection': "Error processing selection. Please try again.",
        # Upgrade Command Text
        'upgrade_title': "Select the plan you want to upgrade to:",
        'upgrade_basic_desc': "💎 **Basic Plan (€{price}/month):**\n- {limit} messages/day",
        'upgrade_premium_desc': "👑 **Premium Plan (€{price}/month):**\n- {limit} messages/day",
        'upgrade_footer': "*You will be redirected to Stripe to complete the secure payment.*",
        'error_stripe_ids_missing': "Sorry, the plan upgrade option is not configured correctly.",
        # Explain Conversation
        'explain_entry_prompt': "Claro, puedo ayudarte con eso. ¿Sobre qué tema específico (DPDR, ansiedad, un síntoma concreto, etc.) te gustaría que preparara una explicación sencilla para compartir?",
        'explain_cancel_instruction': "(Puedes escribir /cancel para detener esto en cualquier momento)",
        'explain_wait': "Vale, preparando una explicación sobre '{topic}'... Dame un momento.",
        'explain_response_header': "Aquí tienes una propuesta de explicación que puedes compartir o adaptar:",
        'explain_response_footer': "Espero que sea útil. ¿Puedo ayudarte con algo más?",
        'explain_cancel_confirmation': "De acuerdo, cancelamos la preparación de la explicación. Puedes usar /faq cuando quieras.",
        'error_stripe_session': "Sorry, there was an error generating the payment link. Please try again later.",
        'error_stripe_specific': "Payment Error: {error}", # <-- Added
        'processing_request': "🧠 Processing your request... Please wait a moment.", # <-- Added
        'consulting_knowledge_base': "Consulting the knowledge base... 🧠 Please wait a few moments while I prepare your answer.", # <-- Added
    }
}

def get_text(key: str, lang_code: str | None = 'en', **kwargs) -> str:
    """Obtiene el texto traducido basado en el código de idioma y formatea con kwargs."""
    lang = lang_code if lang_code in LOCALES else 'en'
    text_template = LOCALES.get(lang, {}).get(key, key)
    try:
        return text_template.format(**kwargs)
    except KeyError as e:
        logging.warning(f"[i18n] Missing format key '{e}' for text key '{key}' in lang '{lang}'")
        return text_template # Devuelve sin formatear si falta una clave
# --- Fin i18n --- 

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

        conn = get_db_connection() # Usar la función helper
        c = conn.cursor()
        # Crear tabla de usuarios si no existe, incluyendo todos los campos finales
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                plan TEXT DEFAULT 'FREE',
                expiry_date TEXT,
                daily_messages INTEGER DEFAULT 0, -- Nombre final
                token_count INTEGER DEFAULT 0,
                last_reset_date TEXT,
                openai_thread_id TEXT         -- Nombre final
            )
        """)

        # --- Bloques ALTER TABLE para users ---

        # Renombrar message_count a daily_messages si existe
        try:
            c.execute("SELECT daily_messages FROM users LIMIT 1")
        except sqlite3.OperationalError: # Si daily_messages no existe...
            try:
                c.execute("ALTER TABLE users RENAME COLUMN message_count TO daily_messages")
                logging.info("Columna 'message_count' renombrada a 'daily_messages'.")
            except sqlite3.OperationalError as e:
                 if "no such column: message_count" in str(e):
                    try:
                         c.execute("ALTER TABLE users ADD COLUMN daily_messages INTEGER DEFAULT 0")
                         logging.info("Columna 'daily_messages' añadida (tabla antigua sin conteo o nueva).")
                    except sqlite3.OperationalError as e_add:
                        if "duplicate column name" not in str(e_add): raise e_add
                 else: raise e

        # Renombrar thread_id a openai_thread_id si existe
        try:
            c.execute("SELECT openai_thread_id FROM users LIMIT 1")
        except sqlite3.OperationalError:
            try:
                c.execute("ALTER TABLE users RENAME COLUMN thread_id TO openai_thread_id")
                logging.info("Columna 'thread_id' renombrada a 'openai_thread_id'.")
            except sqlite3.OperationalError as e:
                if "no such column: thread_id" in str(e):
                     try:
                         c.execute("ALTER TABLE users ADD COLUMN openai_thread_id TEXT")
                         logging.info("Columna 'openai_thread_id' añadida.")
                     except sqlite3.OperationalError as e_add:
                         if "duplicate column name" not in str(e_add): raise e_add
                else: raise e

        # Añadir columnas de información de usuario si no existen
        user_info_columns = ['username', 'first_name', 'last_name', 'language_code']
        for col in user_info_columns:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                logging.info(f"Columna '{col}' añadida a la tabla 'users'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e): raise e

        # Crear tabla de feedback si no existe, con todos los campos finales
        c.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_query TEXT,             -- Nombre final
                assistant_response TEXT,   -- Nombre final
                rating TEXT,
                timestamp TEXT,
                assistant_id TEXT,
                thread_id TEXT,
                run_id TEXT
            )
        """)

        # --- ALTER TABLE para feedback ---
        feedback_columns = {
            'user_query': 'TEXT',
            'assistant_response': 'TEXT',
            'assistant_id': 'TEXT',
            'thread_id': 'TEXT',
            'run_id': 'TEXT'
        }
        # Renombrar message a assistant_response si existe
        try:
            c.execute("SELECT assistant_response FROM feedback LIMIT 1")
        except sqlite3.OperationalError:
             try:
                 c.execute("ALTER TABLE feedback RENAME COLUMN message TO assistant_response")
                 logging.info("Columna 'message' renombrada a 'assistant_response' en feedback.")
             except sqlite3.OperationalError as e:
                 if "no such column: message" in str(e):
                     try:
                        c.execute("ALTER TABLE feedback ADD COLUMN assistant_response TEXT")
                        logging.info("Columna 'assistant_response' añadida a feedback.")
                     except sqlite3.OperationalError as e_add:
                        if "duplicate column name" not in str(e_add): raise e_add
                 else: raise e

        # Añadir el resto de columnas nuevas a feedback si no existen
        for col, col_type in feedback_columns.items():
            if col == 'assistant_response': continue # Ya manejada
            try:
                c.execute(f"ALTER TABLE feedback ADD COLUMN {col} {col_type}")
                logging.info(f"Columna '{col}' añadida a la tabla 'feedback'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e): raise e

        conn.commit()
        logging.info("✅ Base de datos SQLite inicializada/verificada.")
    except sqlite3.Error as e:
        logging.error(f"❌ Error inicializando SQLite: {str(e)}")
        raise e
    finally:
        if conn:
            conn.close()

def add_user(user_id: int):
    """Añade un usuario nuevo a la base de datos si no existe."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        today = date.today().isoformat()
        # Solo insertamos user_id y last_reset_date inicialmente. El resto se llena en /start
        c.execute("INSERT OR IGNORE INTO users (user_id, last_reset_date, daily_messages) VALUES (?, ?, 0)",
                  (user_id, today))
        conn.commit()
        logging.info(f"Usuario {user_id} añadido o ya existente.")
    except sqlite3.Error as e:
        logging.error(f"Error añadiendo usuario {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def get_user(user_id: int):
    """Obtiene los datos del usuario de la base de datos, reseteando contadores si es necesario."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Seleccionar todas las columnas necesarias con los nombres correctos
        c.execute("""SELECT user_id, username, first_name, last_name, language_code,
                          plan, expiry_date, daily_messages, token_count, last_reset_date,
                          openai_thread_id
                   FROM users WHERE user_id = ?""", (user_id,))
        user_data = c.fetchone()

        if user_data:
            today = date.today()
            last_reset = date.fromisoformat(user_data['last_reset_date']) if user_data['last_reset_date'] else today - timedelta(days=1) # Manejar None inicial

            if last_reset < today:
                c.execute("UPDATE users SET daily_messages = 0, token_count = 0, last_reset_date = ? WHERE user_id = ?",
                          (today.isoformat(), user_id))
                conn.commit()
                # Volver a obtener los datos actualizados
                c.execute("""SELECT user_id, username, first_name, last_name, language_code,
                                  plan, expiry_date, daily_messages, token_count, last_reset_date,
                                  openai_thread_id
                           FROM users WHERE user_id = ?""", (user_id,))
                user_data = c.fetchone()
        else:
            logging.warning(f"Usuario {user_id} no encontrado en get_user. Será añadido en el próximo /start.")
            # Ya no añadimos aquí, se hace en /start

        return user_data # Devuelve un objeto Row o None
    except sqlite3.Error as e:
        logging.error(f"Error obteniendo usuario {user_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def update_user_usage(user_id: int, message_increment: int = 1, token_increment: int = 0):
    """Actualiza el uso del usuario en la base de datos."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Usar el nombre de columna correcto: daily_messages
        c.execute("""
            UPDATE users
            SET daily_messages = daily_messages + ?,
                token_count = token_count + ?
            WHERE user_id = ?
        """, (message_increment, token_increment, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error actualizando uso para usuario {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def update_user_plan(user_id: int, plan: str, expiry_date_iso: str | None):
    """Actualiza el plan y la fecha de expiración de un usuario."""
    conn = None # Inicializar conn
    try:
        conn = get_db_connection()
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
        if conn:
            conn.close()

def add_feedback(
    user_id: int,
    user_query: str,
    assistant_response: str,
    rating: str,
    assistant_id: str,
    thread_id: str,
    run_id: str
):
    """Guarda el feedback del usuario en la base de datos."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        # Usar los nombres correctos de las columnas
        c.execute("""INSERT INTO feedback
                     (user_id, user_query, assistant_response, rating, timestamp, assistant_id, thread_id, run_id)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (user_id, user_query, assistant_response, rating, timestamp, assistant_id, thread_id, run_id))
        conn.commit()
        logging.info(f"Feedback guardado para usuario {user_id}: {rating}")
    except sqlite3.Error as e:
        logging.error(f"Error guardando feedback para usuario {user_id}: {e}")
    finally:
        if conn:
            conn.close()

def get_recent_feedback(limit: int = 5):
    """Obtiene las últimas 'limit' entradas de feedback de la base de datos."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Seleccionar las columnas correctas
        c.execute("""SELECT id, user_id, user_query, assistant_response, rating, timestamp,
                          assistant_id, thread_id, run_id
                   FROM feedback ORDER BY timestamp DESC LIMIT ?""", (limit,))
        feedback_data = c.fetchall()
        return feedback_data
    except sqlite3.Error as e:
        logging.error(f"Error obteniendo feedback: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_all_users(plan_filter: str | None = None):
    """Obtiene todos los usuarios, opcionalmente filtrados por plan."""
    conn = None
    try:
        conn = get_db_connection()
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

def get_db_connection(): # <-- Definir la función faltante
    """Establece conexión con la base de datos SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Para devolver filas como diccionarios
    return conn

def update_user_thread_id(user_id: int, thread_id: str | None):
    """Actualiza o borra el thread_id de OpenAI para un usuario."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Usar el nombre de columna correcto: openai_thread_id
        c.execute("UPDATE users SET openai_thread_id = ? WHERE user_id = ?", (thread_id, user_id))
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
ASK_SUPPORT_DETAILS = range(1) # Estado para la conversación de soporte

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

async def process_user_input(user_id: int, lang: str, message_text: str, context: ContextTypes.DEFAULT_TYPE, update: Update):
    """Lógica principal para procesar una entrada de texto del usuario (mensaje o botón FAQ)."""
    
    # --- Bloqueo para solicitudes concurrentes ---
    user_context = context.user_data.setdefault(user_id, {}) # Asegurar que el diccionario existe
    if user_context.get('is_processing', False):
        wait_message = get_text('error_request_in_progress', lang, default="Estoy procesando tu solicitud anterior. Por favor, espera un momento antes de enviar una nueva.")
        if update.callback_query:
             # Responder al callback y enviar mensaje
             await update.callback_query.answer(wait_message, show_alert=True) 
        else:
             await update.message.reply_text(wait_message)
        return
    # --- Fin Bloqueo ---
    
    user_context['is_processing'] = True # Marcar como procesando
    
    try:
        # 0. Usar get_user que maneja creación/actualización de contadores
        user_data = get_user(user_id)
        if not user_data:
            user_context['is_processing'] = False # Desbloquear en caso de error temprano
            await update.message.reply_text(get_text('error_no_user_data', lang))
            return

        current_plan = user_data['plan']
        daily_messages = user_data['daily_messages']
        thread_id_from_db = user_data['openai_thread_id'] 
        plan_limit = SUBSCRIPTION_PLANS.get(current_plan.upper(), {}).get('daily_messages', 0)

        # 1. Verificar límite de mensajes
        if daily_messages >= plan_limit:
            user_context['is_processing'] = False # Desbloquear
            plan_name = current_plan.capitalize()
            limit_msg_1 = get_text('limit_reached_1', lang)
            limit_msg_2 = get_text('limit_reached_2', lang).format(plan_name=plan_name, limit=plan_limit)
            limit_cta = get_text('limit_reached_cta', lang)
            full_limit_message = f"{limit_msg_1}\n{limit_msg_2}\n\n{limit_cta}"
            if update.callback_query:
                 await update.callback_query.answer() # Responder primero al callback
                 await update.callback_query.message.reply_text(full_limit_message, parse_mode=ParseMode.MARKDOWN)
            else:
                 await update.message.reply_text(full_limit_message, parse_mode=ParseMode.MARKDOWN)
            return

        # 2. Incrementar contador de mensajes (usando la función helper)
        update_user_usage(user_id, message_increment=1)

        # --- Lógica OpenAI --- 
        client = user_context.get('openai_client') # Obtener de user_context
        current_thread_id = user_context.get('openai_thread_id') # Obtener de user_context

        if not client or not current_thread_id:
            logging.warning(f"Cliente OpenAI o thread_id no encontrados en context.user_data para {user_id}. Reintentando desde la BD.")
            client = OpenAI(api_key=OPENAI_API_KEY, timeout=httpx.Timeout(60.0))
            current_thread_id = thread_id_from_db
            if not current_thread_id:
                logging.info(f"Creando nuevo thread para {user_id} dentro de process_user_input.")
                thread = client.beta.threads.create()
                current_thread_id = thread.id
                update_user_thread_id(user_id, current_thread_id)
            
            user_context['openai_client'] = client
            user_context['openai_thread_id'] = current_thread_id

        # -- Sub-Try para la interacción OpenAI específica --
        try:
            use_gpt4 = False
            # TODO: Re-evaluar si necesitamos CHECK_CRITICAL_KEYWORDS globalmente
            # if CHECK_CRITICAL_KEYWORDS: 
            #     for keyword in CRITICAL_KEYWORDS:
            #         if re.search(r'\b' + re.escape(keyword) + r'\b', message_text, re.IGNORECASE):
            #             use_gpt4 = True
            #             logging.warning(f"Palabra clave crítica detectada del usuario {user_id}. Usando GPT-4o.")
            #             break

            # TODO: Implementar selección de modelo (gpt-4o vs gpt-4o-mini)
            # model_to_use = "gpt-4o" if use_gpt4 else "gpt-4o-mini"

            logging.info(f"Enviando mensaje del usuario {user_id} al thread {current_thread_id}: '{message_text[:50]}...'")
            client.beta.threads.messages.create(
                thread_id=current_thread_id,
                role="user",
                content=message_text, 
            )

            # --- Construir instrucciones finales --- 
            final_instructions = BASE_INSTRUCTIONS + f" Responde siempre en {lang}." + NO_CITATION_INSTRUCTION
            logging.debug(f"Instrucciones para OpenAI (process_user_input): {final_instructions}")
            # -------------------------------------

            # --- Enviar mensaje de espera --- 
            wait_msg_text = get_text('consulting_knowledge_base', lang) # <-- Usar nueva clave
            if update.callback_query:
                 # No enviar mensaje de espera si es un callback
                 pass 
            else:
                 await update.message.reply_text(wait_msg_text)
            # ----------------------------------

            run = client.beta.threads.runs.create(
                thread_id=current_thread_id,
                assistant_id=ASSISTANT_ID,
                instructions=final_instructions, # <-- Pasar instrucciones
                # model=model_to_use 
            )

            run_id = run.id
            while run.status not in ["completed", "failed", "cancelled", "expired"]:
                await asyncio.sleep(1)
                run = client.beta.threads.runs.retrieve(thread_id=current_thread_id, run_id=run.id)
                logging.debug(f"Run status para user {user_id}: {run.status}")

            if run.status == "completed":
                messages = client.beta.threads.messages.list(thread_id=current_thread_id, order="desc", limit=1)
                assistant_message = messages.data[0].content[0].text.value
                logging.info(f"Respuesta recibida del asistente para el usuario {user_id}")
                
                # Asegurar que user_context existe antes de guardar
                user_context['last_assistant_message_info'] = {
                     'user_query': message_text,
                     'assistant_response': assistant_message,
                     'thread_id': current_thread_id,
                     'run_id': run_id
                 }

                keyboard = [
                    [InlineKeyboardButton(get_text('feedback_useful', lang), callback_data='feedback_useful')],
                    [InlineKeyboardButton(get_text('feedback_not_useful', lang), callback_data='feedback_not_useful')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                     # Es importante responder al callback original si aún no se ha hecho
                     try: await update.callback_query.answer() 
                     except Exception: pass # Ignorar si ya se respondió (p.ej. en bloqueo)
                     await update.callback_query.message.reply_text(assistant_message, reply_markup=reply_markup)
                else:
                     await update.message.reply_text(assistant_message, reply_markup=reply_markup)

            else:
                logging.error(f"La ejecución del asistente falló para el usuario {user_id} con estado: {run.status}")
                error_text = get_text('error_openai_run', lang, default="Lo siento, no pude procesar tu solicitud en este momento.")
                if update.callback_query:
                    try: await update.callback_query.answer() 
                    except Exception: pass
                    await update.callback_query.message.reply_text(error_text)
                else:
                     await update.message.reply_text(error_text)

        except Exception as e_openai:
            logging.error(f"Error durante la interacción con OpenAI para {user_id}: {e_openai}", exc_info=True)
            error_message = get_text('error_generic', lang).format(error=str(e_openai))
            if update.callback_query:
                try: await update.callback_query.answer() 
                except Exception: pass
                await update.callback_query.message.reply_text(error_message)
            else:
                 await update.message.reply_text(error_message)
                 
    finally:
         # Asegurarse de desbloquear al usuario independientemente del resultado
         user_context['is_processing'] = False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verificar si el usuario ya existe
    cursor.execute("""SELECT user_id, username, first_name, last_name, language_code,
                          plan, expiry_date, daily_messages, token_count, last_reset_date,
                          openai_thread_id
                   FROM users WHERE user_id = ?""", (user_id,))
    user_data = cursor.fetchone()
    current_thread_id = None # Inicializar

    if not user_data:
        today_date = date.today()
        expiry_date = today_date + timedelta(days=365*10)
        # Insertar todos los campos disponibles al crear
        cursor.execute(
            """INSERT INTO users (user_id, username, first_name, last_name, language_code,
                               plan, expiry_date, daily_messages, last_reset_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (user_id, user.username, user.first_name, user.last_name, lang,
             'free', expiry_date.isoformat(), today_date.isoformat())
        )
        conn.commit()
        logging.info(f"Nuevo usuario {user_id} ({user.username}) añadido con plan 'free'.")
        # El thread_id sigue siendo None aquí
    else:
        current_thread_id = user_data['openai_thread_id'] # Usar el nombre correcto aquí
        # Actualizar info básica si ha cambiado
        cursor.execute(
            """UPDATE users SET username = ?, first_name = ?, last_name = ?, language_code = ?
               WHERE user_id = ?""",
            (user.username, user.first_name, user.last_name, lang, user_id)
        )
        conn.commit()

    client = OpenAI(api_key=OPENAI_API_KEY, timeout=httpx.Timeout(60.0))
    if not current_thread_id: # Usar la variable que ya contiene el thread_id o None
        thread = client.beta.threads.create()
        current_thread_id = thread.id
        # Usar update_user_thread_id para encapsular la lógica de actualización
        update_user_thread_id(user_id, current_thread_id)
        logging.info(f"Nuevo OpenAI thread creado para el usuario {user_id}: {current_thread_id}")

    context.user_data['openai_thread_id'] = current_thread_id
    context.user_data['openai_client'] = client

    # No necesitamos cerrar la conexión aquí si la obtuvimos de get_db_connection y update_user_thread_id la maneja
    # conn.close() <-- Eliminar si get_db_connection y otras funciones manejan su conexión

    # Enviar mensaje de bienvenida usando get_text
    welcome_text_1 = get_text('start_welcome_1', lang)
    welcome_text_2 = get_text('start_welcome_2', lang)
    commands_title = get_text('start_commands_title', lang)
    faq_cmd = get_text('start_faq', lang)
    plan_cmd = get_text('start_plan', lang)
    upgrade_cmd = get_text('start_upgrade', lang)
    reset_cmd = get_text('start_reset', lang)
    help_cmd = get_text('start_help', lang)
    cta_text = get_text('start_cta', lang)

    full_message = (
        f"{welcome_text_1}\n"
        f"{welcome_text_2}\n\n"
        f"{commands_title}\n"
        f"{faq_cmd}\n"
        f"{plan_cmd}\n"
        f"{upgrade_cmd}\n"
        f"{reset_cmd}\n"
        f"{help_cmd}\n\n"
        f"{cta_text}"
    )

    await update.message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'
    message_text = update.message.text

    # --- Comprobar si el texto es un botón FAQ conocido --- 
    faq_keys = ['faq_understand_dpdr', 'faq_general_anxiety', 'faq_symptoms', 
                'faq_exercises', 'faq_explain_other', 'faq_resources']
    is_faq_button = False
    for key in faq_keys:
        if message_text == get_text(key, lang):
            is_faq_button = True
            break
    # -----------------------------------------------------

    # Si NO es un botón FAQ, o si es CUALQUIER otro texto, procesarlo normalmente
    # (La lógica de FAQ dentro de process_user_input ya no es necesaria si usamos este método)
    await process_user_input(user.id, lang, message_text, context, update)

    # Si es un botón de FAQ, podrías querer quitar el teclado después de procesar
    # if is_faq_button:
    #    await update.message.reply_text(get_text('faq_response_loading', lang, default="Procesando tu selección..."), 
    #                                 reply_markup=ReplyKeyboardRemove())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = user.language_code or 'en'

    help_text = (
        f"{get_text('help_title', lang)}\n"
        f"{get_text('start_faq', lang)}\n"
        f"{get_text('start_plan', lang)}\n"
        f"{get_text('start_upgrade', lang)}\n"
        f"{get_text('start_reset', lang)}\n"
        f"{get_text('start_help', lang)}\n"
        f"{get_text('help_support', lang)}"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'

    # Usar la función helper para actualizar la BD
    success = update_user_thread_id(user_id, None)

    if success:
        if 'openai_thread_id' in context.user_data:
            del context.user_data['openai_thread_id']
        if 'openai_client' in context.user_data:
             # Podríamos mantener el cliente, o reiniciarlo la próxima vez
             del context.user_data['openai_client']
        logging.info(f"Conversación reseteada para el usuario {user_id}. El próximo mensaje creará un nuevo thread.")
        await update.message.reply_text(get_text('reset_confirmation', lang))
    else:
        # Informar al usuario si falla la actualización en BD?
        await update.message.reply_text("Hubo un problema al intentar reiniciar tu conversación.")

async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = user.language_code or 'en'

    # --- Volver a ReplyKeyboardMarkup --- 
    keyboard = [
        [get_text('faq_understand_dpdr', lang), get_text('faq_general_anxiety', lang)],
        [get_text('faq_symptoms', lang), get_text('faq_exercises', lang)],
        [get_text('faq_explain_other', lang), get_text('faq_resources', lang)]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    # ------------------------------------
    
    # --- Texto original de descripción --- 
    text_lines = [
        get_text('faq_area_understand', lang),
        get_text('faq_area_anxiety', lang),
        get_text('faq_area_explain', lang),
        get_text('faq_area_symptoms', lang),
        get_text('faq_area_exercises', lang),
        get_text('faq_area_resources', lang),
        "\n" + get_text('faq_select_area', lang) 
    ]
    faq_text = "\n".join(text_lines)
    # -----------------------------------

    # Enviar mensaje con el teclado de respuesta
    await update.message.reply_text(faq_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra opciones para actualizar el plan con botones inline."""
    # --- Nueva obtención de idioma ---
    user = update.effective_user
    lang = user.language_code or 'en'
    # ---------------------------------

    # --- Usar constantes para los Price IDs --- 
    basic_price_id = os.getenv('STRIPE_PRICE_ID_BASIC')
    premium_price_id = os.getenv('STRIPE_PRICE_ID_PREMIUM')
    # ----------------------------------------

    if not basic_price_id or not premium_price_id:
        # Traducir error
        error_msg = get_text('error_stripe_ids_missing', lang, default="Lo siento, la opción de mejora de plan no está configurada correctamente.")
        await update.message.reply_text(error_msg)
        logging.error("IDs de precios de Stripe (BASIC o PREMIUM) no configurados en variables de entorno.")
        return
        
    # --- Obtener precios y límites desde SUBSCRIPTION_PLANS ---
    basic_plan = SUBSCRIPTION_PLANS.get('BASIC', {})
    premium_plan = SUBSCRIPTION_PLANS.get('PREMIUM', {})
    basic_price = basic_plan.get('price', 'N/A')
    premium_price = premium_plan.get('price', 'N/A')
    basic_limit = basic_plan.get('daily_messages', 'N/A')
    premium_limit = premium_plan.get('daily_messages', 'N/A')
    # ------------------------------------------------------
    
    keyboard = [
        [
            # Usar constantes obtenidas
            InlineKeyboardButton(f"💎 Plan Basic - {basic_price}€/mes", callback_data=f"upgrade_basic_{basic_price_id}"),
        ],
        [
            # Usar constantes obtenidas
            InlineKeyboardButton(f"👑 Plan Premium - {premium_price}€/mes", callback_data=f"upgrade_premium_{premium_price_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # --- Usar get_text para el mensaje ---
    title = get_text('upgrade_title', lang, default="Selecciona el plan al que quieres actualizar:")
    basic_desc = get_text('upgrade_basic_desc', lang, default="💎 **Plan Basic ({price}€/mes):**\n- {limit} mensajes/día").format(price=basic_price, limit=basic_limit)
    premium_desc = get_text('upgrade_premium_desc', lang, default="👑 **Plan Premium ({price}€/mes):**\n- {limit} mensajes/día").format(price=premium_price, limit=premium_limit)
    footer = get_text('upgrade_footer', lang, default="*Serás redirigido a Stripe para completar el pago seguro.*")
    
    message_text = f"{title}\n\n{basic_desc}\n\n{premium_desc}\n\n{footer}"
    # -----------------------------------

    await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

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

async def upgrade_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    lang = user.language_code or 'en'
    
    # Log de entrada y datos recibidos
    logging.info(f"upgrade_button_handler: Entrando para user {user_id}. Callback data: '{query.data}'")
    
    await query.answer() # Responde al callback

    try:
        parts = query.data.split('_')
        if len(parts) < 3 or parts[0] != 'upgrade':
             raise ValueError("Formato de callback_data incorrecto")
        plan_type = parts[1] # 'basic' or 'premium'
        price_id = '_'.join(parts[2:]) 
        logging.info(f"upgrade_button_handler: Parsed plan_type='{plan_type}', price_id='{price_id}'")
    except (IndexError, ValueError) as e:
        logging.error(f"upgrade_button_handler: Error parseando callback_data '{query.data}': {e}")
        error_text = get_text('error_processing_selection', lang, default="Error procesando la selección. Inténtalo de nuevo.")
        try:
             await query.edit_message_text(error_text)
        except Exception as edit_e:
             logging.warning(f"upgrade_button_handler: No se pudo editar mensaje de error: {edit_e}")
        return

    if not price_id:
        logging.error(f"upgrade_button_handler: Price ID vacío después de parsear para plan '{plan_type}' desde callback_data '{query.data}'")
        error_text = get_text('error_price_id_not_found', lang, default="Error: No se encontró el ID de precio para ese plan.")
        try:
            await query.edit_message_text(error_text)
        except Exception as edit_e:
             logging.warning(f"upgrade_button_handler: No se pudo editar mensaje de error ID vacío: {edit_e}")
        return

    logging.info(f"upgrade_button_handler: Extracted Price ID from callback: '{price_id}' for plan {plan_type}")

    progress_text = get_text('upgrade_generating_link', lang, default="Generando enlace de pago seguro...")
    try:
        await query.edit_message_text(progress_text)
    except Exception as edit_e:
        logging.warning(f"upgrade_button_handler: No se pudo editar mensaje de progreso: {edit_e}")

    try:
        # --- Log URLs antes de llamar a Stripe --- 
        constructed_success_url = YOUR_DOMAIN + '/success?session_id={CHECKOUT_SESSION_ID}'
        constructed_cancel_url = YOUR_DOMAIN + '/cancel'
        logging.info(f"upgrade_button_handler: Construyendo URLs para Stripe: success='{constructed_success_url}', cancel='{constructed_cancel_url}'")
        # -------------------------------------------
        logging.info(f"upgrade_button_handler: Intentando crear sesión de Stripe con Price ID: {price_id}")
        
        # --- Configurar timeout para Stripe --- 
        stripe.timeout = 30 # 30 segundos de timeout
        # --------------------------------------
        
        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=constructed_success_url, # Usar variable
            cancel_url=constructed_cancel_url,   # Usar variable
            customer_email=None, 
            metadata={
                'telegram_user_id': str(user_id) 
            }
            # request_options={ 'timeout': 30 } # Otra forma de pasar timeout específico
        )
        # --- Log URL de sesión devuelta --- 
        session_url = checkout_session.url
        logging.info(f"upgrade_button_handler: Sesión de Stripe creada: {checkout_session.id}. URL: {session_url}")
        # ----------------------------------

        payment_link_text = get_text('upgrade_payment_link_message', lang, default="Haz clic aquí para completar tu suscripción:")
        # Asegurarse de que session_url no es None antes de usarlo
        if session_url:
            # --- Enviar enlace como Botón Inline --- 
            keyboard = [[InlineKeyboardButton("➡️ Pagar Ahora en Stripe", url=session_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(payment_link_text, reply_markup=reply_markup)
            # ---------------------------------------
            logging.info(f"upgrade_button_handler: Enlace de pago enviado a user {user_id}")
        else:
             logging.error(f"upgrade_button_handler: checkout_session.url devuelta por Stripe es None para session {checkout_session.id}")
             await query.message.reply_text(get_text('error_stripe_session', lang))

    # --- Captura de errores más específica --- 
    except stripe.error.StripeError as e:
        logging.error(f"upgrade_button_handler: Error de Stripe API para user {user_id}: {e}", exc_info=True)
        # Intentar obtener más detalles del error
        err_body = e.json_body.get('error', {})
        user_message = err_body.get('message', "Ocurrió un error con el pago.")
        logging.error(f"StripeError details: status={e.http_status}, type={err_body.get('type')}, code={err_body.get('code')}, param={err_body.get('param')}, message={user_message}")
        # Usar un mensaje más específico si es posible, o el genérico de Stripe
        stripe_error_text = get_text('error_stripe_specific', lang, default=f"Error de pago: {user_message}") 
        try:
             await query.message.reply_text(stripe_error_text)
        except Exception as reply_e:
             logging.error(f"upgrade_button_handler: No se pudo enviar mensaje de error específico de Stripe: {reply_e}")
    # -----------------------------------------
    except Exception as e:
        # Captura genérica para otros errores inesperados
        logging.error(f"upgrade_button_handler: Error inesperado para el usuario {user_id}: {e}", exc_info=True)
        stripe_error_text = get_text('error_stripe_session', lang, default="Lo siento, hubo un error al generar el enlace de pago. Por favor, inténtalo de nuevo más tarde.")
        try:
             await query.message.reply_text(stripe_error_text)
        except Exception as reply_e:
             logging.error(f"upgrade_button_handler: No se pudo enviar mensaje de error genérico de Stripe: {reply_e}")

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'

    # Usar get_user para obtener datos y manejar reset diario
    user_data = get_user(user_id)

    if not user_data:
        await update.message.reply_text(get_text('error_no_user_data', lang))
        return

    # Acceder a los datos usando los nombres de columna correctos de la BD
    current_plan = user_data['plan']
    daily_messages = user_data['daily_messages']
    expiry_date_str = user_data['expiry_date']
    
    plan_name = current_plan.capitalize()
    plan_limit = SUBSCRIPTION_PLANS.get(current_plan.upper(), {}).get('daily_messages', 0)

    expiry_date_formatted = "N/A"
    if expiry_date_str and current_plan.upper() != 'FREE':
        try:
            expiry_date = datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00'))
            expiry_date_formatted = expiry_date.strftime('%d-%m-%Y')
        except ValueError:
            try:
                expiry_date = datetime.strptime(expiry_date_str, '%d-%m-%Y')
                expiry_date_formatted = expiry_date.strftime('%d-%m-%Y')
            except ValueError:
                logging.error(f"Error al parsear la fecha de expiración '{expiry_date_str}' para el usuario {user_id}")
                expiry_date_formatted = get_text('plan_expiry_error', lang, default="Fecha inválida")

    plan_info_title = get_text('plan_title', lang)
    plan_info_name = f"**{plan_name}**"
    # Pasar daily_messages y plan_limit a la plantilla si es necesario
    plan_info_messages = f"{get_text('plan_messages_today', lang)} {daily_messages}/{plan_limit}"
    
    plan_info_expires = ""
    if current_plan.upper() != 'FREE':
        # Pasar expiry_date_formatted como argumento 'expiry_date'
        plan_info_expires = get_text('plan_expires', lang).format(expiry_date=expiry_date_formatted)

    available_plans_title = get_text('plan_available_title', lang)
    
    # Obtener precios y límites
    free_limit = SUBSCRIPTION_PLANS.get('FREE', {}).get('daily_messages', 0)
    basic_limit = SUBSCRIPTION_PLANS.get('BASIC', {}).get('daily_messages', 0)
    premium_limit = SUBSCRIPTION_PLANS.get('PREMIUM', {}).get('daily_messages', 0)
    basic_price = SUBSCRIPTION_PLANS.get('BASIC', {}).get('price', 'N/A')
    premium_price = SUBSCRIPTION_PLANS.get('PREMIUM', {}).get('price', 'N/A')

    # Asegurarse de pasar los argumentos correctos
    plan_free_desc = get_text('plan_free_desc', lang).format(limit=free_limit)
    plan_basic_desc = get_text('plan_basic_desc', lang).format(limit=basic_limit, price=basic_price)
    plan_premium_desc = get_text('plan_premium_desc', lang).format(limit=premium_limit, price=premium_price)

    if current_plan.upper() == 'FREE':
        upgrade_cta = get_text('plan_upgrade_cta_free', lang)
    else:
        upgrade_cta = get_text('plan_upgrade_cta_paid', lang)

    full_message = (
        f"{plan_info_title}\n{plan_info_name}\n{plan_info_messages}\n{plan_info_expires}\n\n"
        f"{available_plans_title}\n"
        f"{plan_free_desc}\n"
        f"{plan_basic_desc}\n"
        f"{plan_premium_desc}\n\n"
        f"{upgrade_cta}"
    )

    await update.message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)

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
    message_count = user_data['daily_messages']
    last_reset = user_data['last_reset_date']

    message = f"ℹ️ **Información del Usuario: {target_user_id}**\n\n"
    message += f"👤 **ID:** `{target_user_id}`\n"
    message += f"🏷️ **Plan:** {current_plan['name']} (`{current_plan_type}`)\n"
    message += f"✉️ **Mensajes Hoy:** {message_count}/{current_plan['daily_messages']}\n"
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
        # update_user_usage(target_user_id, message_increment=-get_user(target_user_id)['daily_messages']) # Reset msg count
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
        safe_message = entry['user_query'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
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
    """Inicia la conversación para explicar algo a otros."""
    user = update.effective_user
    lang = user.language_code or 'en'
    prompt_text = get_text('explain_entry_prompt', lang, default="Claro, puedo ayudarte con eso. ¿Sobre qué tema específico (DPDR, ansiedad, un síntoma concreto, etc.) te gustaría que preparara una explicación sencilla para compartir?")
    cancel_instruction = get_text('explain_cancel_instruction', lang, default="(Puedes escribir /cancel para detener esto en cualquier momento)")
    await update.message.reply_text(f"{prompt_text}\n\n{cancel_instruction}")
    return ASK_EXPLAIN_TARGET

async def explain_target_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe el tema a explicar y genera la explicación."""
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'
    user_topic = update.message.text

    # Verificar límites usando get_user
    user_data = get_user(user_id)
    if not user_data:
        await update.message.reply_text(get_text('error_no_user_data', lang))
        return ConversationHandler.END

    current_plan = user_data['plan']
    daily_messages = user_data['daily_messages']
    thread_id_from_db = user_data['openai_thread_id'] # Nombre correcto
    plan_limit = SUBSCRIPTION_PLANS.get(current_plan.upper(), {}).get('daily_messages', 0)

    if daily_messages >= plan_limit:
        plan_name = current_plan.capitalize()
        limit_msg_1 = get_text('limit_reached_1', lang)
        limit_msg_2 = get_text('limit_reached_2', lang).format(plan_name=plan_name, limit=plan_limit)
        limit_cta = get_text('limit_reached_cta', lang)
        full_limit_message = f"{limit_msg_1}\n{limit_msg_2}\n\n{limit_cta}"
        await update.message.reply_text(full_limit_message, parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    # Incrementar contador
    update_user_usage(user_id, message_increment=1)

    client = context.user_data.get('openai_client')
    current_thread_id = context.user_data.get('openai_thread_id')

    if not client or not current_thread_id:
        logging.warning(f"Cliente OpenAI o thread_id no encontrados en context.user_data para {user_id} en explain_conv. Reintentando.")
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=httpx.Timeout(60.0))
        current_thread_id = thread_id_from_db # Usar el de la BD

        if not current_thread_id:
            logging.info(f"Creando nuevo thread para {user_id} dentro de explain_target_received.")
            thread = client.beta.threads.create()
            current_thread_id = thread.id
            update_user_thread_id(user_id, current_thread_id) # Usar helper

        context.user_data['openai_client'] = client
        context.user_data['openai_thread_id'] = current_thread_id

    # Mensaje de espera (traducir)
    wait_message = get_text('explain_wait', lang, default="Vale, preparando una explicación sobre '{topic}'... Dame un momento.").format(topic=user_topic)
    await update.message.reply_text(wait_message)

    # Instrucción para la IA (sin traducir, es para la IA)
    explain_instruction = (
        f"Actúa como alguien que ayuda a explicar condiciones de salud mental a familiares y amigos de forma muy sencilla y empática. "
        f"El usuario quiere explicar '{user_topic}'. Genera un texto corto (máximo 3-4 párrafos) que el usuario pueda compartir. "
        f"Debe ser fácil de entender para alguien sin conocimientos previos, usando analogías si es posible, validando la experiencia "
        f"y enfocándose en cómo pueden apoyar. Evita jerga técnica compleja. Si el tema es vago, intenta dar una explicación general útil."
    )
    # Añadir instrucción de idioma y limpieza
    final_instructions = explain_instruction + f" Responde siempre en {lang}." + NO_CITATION_INSTRUCTION # <-- Usar constante

    # Lógica de OpenAI (similar a handle_message)
    try:
        # Comprobar palabras clave críticas
        use_gpt4 = False
        if CHECK_CRITICAL_KEYWORDS:
            for keyword in CRITICAL_KEYWORDS:
                 if re.search(r'\b' + re.escape(keyword) + r'\b', user_topic, re.IGNORECASE):
                    use_gpt4 = True
                    logging.warning(f"Palabra clave crítica detectada en explicación ({user_topic}) por usuario {user_id}. Usando GPT-4o.")
                    break
        # TODO: Implementar selección de modelo cuando esté listo

        # Enviar mensaje al hilo
        client.beta.threads.messages.create(
            thread_id=current_thread_id,
            role="user",
            content=f"Generar explicación para familiares/amigos sobre: {user_topic}" # Prompt interno
        )

        # Ejecutar asistente
        run = client.beta.threads.runs.create(
            thread_id=current_thread_id, 
            assistant_id=ASSISTANT_ID, 
            instructions=final_instructions # <-- Asegurarse de pasarla
            # model=... # Añadir selección de modelo aquí
        )

        # Esperar finalización
        while run.status not in ["completed", "failed", "cancelled", "expired"]:
            await asyncio.sleep(1)
            run = client.beta.threads.runs.retrieve(thread_id=current_thread_id, run_id=run.id)
            logging.debug(f"Explain Run status for user {user_id}: {run.status}")

        # Procesar respuesta
        if run.status == "completed":
            messages = client.beta.threads.messages.list(thread_id=current_thread_id, order="desc", limit=1)
            assistant_response = messages.data[0].content[0].text.value
            logging.info(f"Explicación generada para el usuario {user_id}")
            
            # Enviar respuesta (traducir plantilla)
            response_header = get_text('explain_response_header', lang, default="Aquí tienes una propuesta de explicación que puedes compartir o adaptar:")
            response_footer = get_text('explain_response_footer', lang, default="Espero que sea útil. ¿Puedo ayudarte con algo más?")
            
            full_response = f"{response_header}\n\n---\n{assistant_response}\n---\n\n{response_footer}"
            await update.message.reply_text(full_response)

        else:
            logging.error(f"La ejecución de explicación falló para {user_id} con estado: {run.status}")
            error_text = get_text('error_openai_run', lang, default="Lo siento, no pude generar la explicación en este momento.")
            await update.message.reply_text(error_text)

    except Exception as e:
        logging.error(f"Error inesperado al generar explicación para {user_id}: {e}", exc_info=True)
        error_message = get_text('error_generic', lang).format(error=str(e))
        await update.message.reply_text(error_message)

    return ConversationHandler.END

async def explain_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la conversación actual."""
    user = update.effective_user
    lang = user.language_code or 'en'
    cancel_message = get_text('explain_cancel_confirmation', lang, default="De acuerdo, cancelamos la preparación de la explicación. Puedes usar /faq cuando quieras.")
    await update.message.reply_text(cancel_message)
    return ConversationHandler.END

# --- Fin Funciones Conversación ---

async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    lang = user.language_code or 'en'
    await query.answer() # Responde al callback para que el botón deje de cargar

    rating = 'positive' if query.data == 'feedback_useful' else 'negative'
    # Simplificar obtención de last_message_info (asumiendo que se guarda en user_data[user.id])
    last_message_info = context.user_data.get(user.id, {}).get('last_assistant_message_info')

    if last_message_info:
        # Pasar los datos correctos a add_feedback
        add_feedback(
            user_id=user.id,
            user_query=last_message_info.get('user_query', 'N/A'), # Asegurar que existen
            assistant_response=last_message_info.get('assistant_response', 'N/A'),
            rating=rating,
            assistant_id=ASSISTANT_ID, # Ya lo tenemos globalmente
            thread_id=last_message_info.get('thread_id', 'N/A'),
            run_id=last_message_info.get('run_id', 'N/A')
        )
        feedback_response_key = 'feedback_thanks_positive' if rating == 'positive' else 'feedback_thanks_negative'
        feedback_text = get_text(feedback_response_key, lang)
        await query.edit_message_reply_markup(reply_markup=None) # Eliminar botones
        await query.message.reply_text(feedback_text) # Enviar mensaje de agradecimiento
        try:
             # Limpiar la info guardada (asegurarse de que user.id existe como clave)
             if user.id in context.user_data:
                del context.user_data[user.id]['last_assistant_message_info']
        except KeyError:
             logging.warning(f"No se pudo encontrar last_assistant_message_info para limpiar para user {user.id}")
    else:
        # Si no hay info del último mensaje, simplemente agradecer genéricamente
        await query.edit_message_reply_markup(reply_markup=None) # Eliminar botones
        await query.message.reply_text(get_text('feedback_thanks_generic', lang))

# --- Funciones para la Conversación de Soporte ---

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia la conversación de solicitud de soporte."""
    user = update.effective_user
    lang = user.language_code or 'en'
    prompt_text = get_text('support_prompt', lang, default="Por favor, describe brevemente tu consulta o problema para el equipo de soporte:")
    cancel_instruction = get_text('support_cancel_instruction', lang, default="(Escribe /cancel si cambias de opinión)")
    await update.message.reply_text(f"{prompt_text}\n\n{cancel_instruction}")
    return ASK_SUPPORT_DETAILS

async def support_details_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe la consulta de soporte, la notifica a los admins y confirma al usuario."""
    user = update.effective_user
    lang = user.language_code or 'en'
    support_query = update.message.text

    logging.info(f"Recibida consulta de soporte del usuario {user.id} ({user.username}): {support_query}")

    # Formatear notificación para admins
    notification_message = (
        f"📣 **Nueva Consulta de Soporte** 📣\n\n"
        f"**De:** Usuario ID `{user.id}` (Username: @{user.username or 'N/A'})\n"
        f"**Consulta:**\n{support_query}"
    )

    # Enviar notificación a todos los admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=notification_message, parse_mode=ParseMode.MARKDOWN)
            logging.info(f"Notificación de soporte enviada al admin {admin_id}")
        except Exception as e:
            logging.error(f"Error enviando notificación de soporte al admin {admin_id}: {e}")

    # Confirmar al usuario
    confirmation_text = get_text('support_confirmation', lang, default="Gracias. Tu consulta ha sido enviada al equipo de soporte. Te contactarán si es necesario.")
    await update.message.reply_text(confirmation_text)

    return ConversationHandler.END

async def support_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela la conversación de soporte."""
    user = update.effective_user
    lang = user.language_code or 'en'
    cancel_message = get_text('support_cancel_confirmation', lang, default="De acuerdo, se canceló la solicitud de soporte.")
    await update.message.reply_text(cancel_message)
    return ConversationHandler.END

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

        # --- Crear ConversationHandler para Soporte ---
        support_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("support", support_command)],
            states={
                ASK_SUPPORT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_details_received)],
            },
            fallbacks=[CommandHandler('cancel', support_cancel)],
            # Podríamos añadir un timeout aquí también
        )
        # --- Fin ConversationHandler ---

        # Registramos los handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("faq", faq_command))
        application.add_handler(CommandHandler("plan", plan_command))
        application.add_handler(CommandHandler("upgrade", upgrade_command))
        
        # Añadir PRIMERO los ConversationHandlers
        application.add_handler(explain_conv_handler)
        application.add_handler(support_conv_handler) # <-- Añadir handler de soporte

        # --- Añadir Handler para botones de Upgrade --- 
        application.add_handler(CallbackQueryHandler(upgrade_button_handler, pattern='^upgrade_'))
        # --------------------------------------------

        # --- Añadir Handler para botones de Feedback ---
        application.add_handler(CallbackQueryHandler(feedback_callback, pattern='^feedback_'))
        # -------------------------------------------
        
        # --- Añadir Handler para botones de FAQ ---
        # application.add_handler(CallbackQueryHandler(faq_button_handler, pattern='^faq_')) 
        # ---------------------------------------

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

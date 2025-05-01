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
STRIPE_PRICE_ID_GOLD = os.getenv('STRIPE_PRICE_ID_GOLD') # <-- Leer nuevo ID
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
CHECK_CRITICAL_KEYWORDS = True # Poner a True para activar la comprobación

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
        'faq_understand_dpdr': "🧠 Entender DPDR",
        'faq_general_anxiety': "🌀 Ansiedad general",
        'faq_symptoms': "🩺 Síntomas",
        'faq_exercises': "🧘 Ejercicios",
        'faq_explain_other': "🗣️ Explicar a Otros", # Emoji changed
        'faq_resources': "📚 Recursos",
        # FAQ Descriptions (Keep as is for now, could remove later if not needed)
        'faq_select_area': "Selecciona un área de interés:",
        'faq_area_understand': "🧠 **Entender DPDR:** Una explicación tranquilizadora sobre qué es y por qué ocurre.",
        'faq_area_anxiety': "🌀 **Ansiedad general:** Información sobre la ansiedad, sus mecanismos y cómo se manifiesta.",
        'faq_area_explain': "❤️ **Explicar a Otros:** Ayuda para describir tu experiencia (DPDR o ansiedad) a familiares y amigos.",
        'faq_area_symptoms': "🩺 **Síntomas:** Un repaso a los síntomas comunes y qué pueden indicar.",
        'faq_area_exercises': "🧘 **Ejercicios:** Técnicas y ejercicios prácticos para manejar DPDR y ansiedad.",
        'faq_area_resources': "📚 **Recursos:** Enlaces, libros y otros materiales de apoyo.",
        # Fixed FAQ Responses <-- NEW SECTION
        'faq_response_understand_dpdr': """🧩 **Entender DPDR:**

La despersonalización y la desrealización (DPDR) son experiencias extrañas pero inofensivas que muchas personas atraviesan, especialmente en momentos de mucho estrés emocional o psicológico. Son mecanismos de defensa del cerebro, una forma en que la mente trata de protegerte cuando se siente abrumada.

*Despersonalización:* es la sensación de estar desconectado de ti mismo, como si observaras tus pensamientos, tu cuerpo o tus acciones desde afuera, como si fueras un espectador. Puedes sentirte entumecido o como un robot, como si no estuvieras realmente \"dentro\" de tu cuerpo.

*Desrealización:* es la impresión de que el mundo que te rodea no es real, como si estuvieras en un sueño o viendo todo a través de un vidrio. Las cosas pueden parecer extrañas, planas o artificiales.

Aunque estas sensaciones pueden ser muy incómodas y alarmantes, no son peligrosas, no indican que estés perdiendo la cordura, ni significan que haya algo roto en ti. De hecho, son reversibles cuando tu cuerpo y mente comienzan a sentirse seguros nuevamente.

¿Te gustaría una versión más personal o fácil de identificar contigo? (Si es así, simplemente pídelo)""",
        'faq_response_general_anxiety': """🌪️ **Ansiedad General:**

La ansiedad general es una sensación constante de preocupación, nerviosismo o tensión, incluso cuando no hay un peligro real o inmediato. No es solo \"estar un poco estresado\", sino que puede sentirse como si algo malo fuera a pasar, aunque no sepas exactamente qué.

En el **cuerpo**, la ansiedad puede causar cosas como palpitaciones, tensión muscular, dificultad para respirar, dolor en el pecho, o problemas para dormir. Todo esto ocurre porque el cuerpo entra en un estado de "alerta" como si tuviera que defenderse de un peligro, aunque en realidad no lo haya.

En la **mente**, puede hacer que los pensamientos se vuelvan muy repetitivos o negativos. A veces te atrapas en un bucle de pensamientos difíciles, como "¿y si esto no mejora?" o "¿y si me pasa algo?". Esto puede hacer que te sientas desconectado, cansado o abrumado.

La ansiedad se puede volver persistente porque el cuerpo y el cerebro aprenden a estar en ese estado de alerta todo el tiempo. A veces una situación estresante dispara la ansiedad, pero incluso después de que esa situación pasa, el sistema nervioso sigue funcionando como si todavía hubiera una amenaza. Es como si el "botón de alarma" se hubiera quedado atascado.

Pero lo más importante: este estado se puede **reentrenar**. No estás roto. Con el enfoque adecuado, el cuerpo y la mente pueden volver a encontrar la calma.

¿Hay alguna parte de esto sobre la que te gustaría saber más? (Si es así, simplemente pídelo)""",
        'faq_response_symptoms': """🩺**Síntomas:**

Aquí tienes una lista de los síntomas más comunes de la despersonalización/desrealización (DPDR) y la ansiedad, agrupados por tipo:

🧠 **Síntomas Cognitivos (Mentales)**
* Sensación de estar desconectado de uno mismo (como si te vieras desde fuera)
* Percepción de que el mundo no es real, como si fuera un sueño, neblinoso o artificial
* Pensamientos acelerados o excesivos
* Dificultad para concentrarse o problemas de memoria ("mente nublada")
* Miedo a "volverse loco" o perder el control
* Pensamientos obsesivos sobre la existencia, la realidad o uno mismo
* Sensación de confusión o estar mentalmente distante
* pensar demasiado en tu estado también es parte de la ansiedad

💬 **Síntomas Emocionales**
* Entumecimiento emocional (sentirse plano o como un "robot")
* Miedo constante o sensación de amenaza
* Sentirse desconectado de personas cercanas
* Sensación de desesperanza o tristeza
* Irritabilidad o sensibilidad emocional
* Cambios de humor o sensación de estar emocionalmente abrumado

🧍‍♂️ **Síntomas Físicos**
* Opresión en el pecho o dificultad para respirar
* Palpitaciones o latidos rápidos
* Tensión en cuello, hombros o mandíbula
* Mareo o sensación de inestabilidad
* Hormigueo o entumecimiento en manos, cara o cuerpo
* Temblores o debilidad
* Problemas digestivos (náuseas, hinchazón, retortijones)
* Dificultad para dormir o sueño poco reparador
* Sacudidas internas o sobresaltos al tratar de relajarse
* Sensación de irrealidad al mirarse al espejo

Si me cuentas qué síntomas tienes, puedo ayudarte a entender qué podrían significar.""",
        'faq_response_exercises': """🧘‍♂️ **Ejercicios:**

Cuando te sientes desconectado, ansioso o abrumado, tu cuerpo y tu mente suelen estar atrapados en un estado de "modo supervivencia". Los ejercicios simples de respiración o de anclaje (grounding) pueden enviarle al sistema nervioso una señal de que estás a salvo, ayudándote a volver al momento presente y a reconectarte contigo mismo y con tu entorno. No son soluciones mágicas, pero sí herramientas muy útiles para recuperar la calma y el equilibrio.

Aquí tienes algunos ejercicios que puedes probar:

🌿 **1. Técnica 5-4-3-2-1**
Nombra:
- **5 cosas que puedes ver**
- **4 cosas que puedes tocar**
- **3 cosas que puedes oír**
- **2 cosas que puedes oler**
- **1 cosa que puedes saborear**
Este ejercicio te ayuda a volver al presente usando tus sentidos.

🌬️ **2. Respiración en caja**
Inhala durante **4 segundos**,
Mantén el aire durante **4 segundos**,
Exhala durante **4 segundos**,
Mantén sin aire otros **4 segundos**.
Repite varias veces para relajar cuerpo y mente.

✋ **3. Respiración con contacto corporal**
Coloca una mano en el pecho y otra en el abdomen.
Respira lentamente, sintiendo cómo tus manos suben y bajan.
Esto te ayuda a reconectar con tu cuerpo de forma suave.

¿Quieres que te recomiende uno según cómo te estás sintiendo ahora? (Si es así, pídelo)""",
        'faq_response_explain_other': """🗣️ **Explicar a Otros:**

Estoy atravesando algo llamado despersonalización y desrealización. A veces siento como si estuviera fuera de mi cuerpo o como si todo a mi alrededor no fuera real. Sé que suena raro, pero no es peligroso ni significa que me esté volviendo loco.

Lo que pasa es que, cuando estamos muy estresados o ansiosos, el cerebro puede activar una especie de 'modo de emergencia'. Es una reacción automática y muy antigua del sistema nervioso, conocida como **respuesta de congelamiento** ('freeze' en inglés).

Esta respuesta viene de nuestros antepasados. Cuando un animal no podía ni huir ni luchar, su cuerpo se "apagaba" o se desconectaba para protegerse del dolor o del trauma. Es un mecanismo de defensa.

En mi caso, aunque no haya un peligro real, mi sistema nervioso sigue respondiendo como si lo hubiera, y eso genera esta sensación tan extraña de desconexión.

La buena noticia es que esto se puede revertir. No es algo permanente. Con calma, comprensión y las herramientas adecuadas, el cuerpo y la mente pueden volver a sentirse seguros y presentes.

Lo que más me ayuda es sentirme acompañado y escuchado, incluso si no lo entendés del todo.

¿Quieres que lo adapte más a cómo tú lo vives? Puedo ayudarte con eso.""",
        'faq_response_resources': """📚**Recursos:**

📚 **Libros**
- *The Depersonalization Manual* – Shaun O'Connor
- *Overcoming Depersonalization Disorder* – Fugen Neziroglu & Katharine Donnelly
- *Feeling Unreal* – Daphne Simeon & Jeffrey Abugel
- *Stop Unreality* – Kevin Klix
- *The Body Keeps the Score* – Bessel van der Kolk (trauma-informed perspective)

🌐 **Websites & Online Resources**
- [**dpmanual.com**](https://www.dpmanual.com/) – Shaun O'Connor's recovery guide
- [**unrealuk.org**](https://www.unrealuk.org/) – UK charity focused on DPDR
- [**anxietycentre.com**](https://www.anxietycentre.com/) – In-depth anxiety education and tools
- [**NAMI.org**](https://www.nami.org/) – General mental health resources
- [**YouTube: Jordan Hardgrave**](https://www.youtube.com/@JordanHardgrave) – Trauma and anxiety education

💬 **Forums & Communities**
- [**Reddit: r/DPDR**](https://www.reddit.com/r/DPDR/) – Peer support and shared experiences
- [**No More DP**](https://www.nomoredp.com/) – Community and tools from a recovered DPDR sufferer
- **HealthUnlocked: Anxiety Support** – Discussion forums

🧘‍♂️ **Apps & Tools**
- **Insight Timer** – Guided meditations for grounding and anxiety
- **CBT Thought Diary** – Cognitive behavioral therapy journaling
- **MindShift CBT** – Coping tools for anxiety
- **DARE: Break Free from Anxiety** – Based on the DARE method

🗣️ *If you'd like any of these resources in a specific language, let me know and I'll help you find them.*""",
        'faq_back_button': "⬅️ Volver al menú FAQ",
        # Feedback
        'feedback_useful': "👍 Útil",
        'feedback_not_useful': "👎 No útil",
        'feedback_prompt': "¿Te ha resultado útil esta respuesta?",
        'feedback_thanks_positive': "¡Gracias por tu feedback positivo! 👍",
        'feedback_thanks_negative': "Gracias por tu feedback. Lo tendremos en cuenta para mejorar. 👍",
        'feedback_thanks_generic': "Gracias por tu feedback.", 
        # Comandos
        'start_welcome_1': "¡Hola! Soy un guía especializado en la ansiedad y especialmente en sus síntomas DPDR (despersonalización y desrealización).",
        'start_welcome_2': "Puedo ayudarte con información y consejos basados en guías y recursos especializados.",
        'start_ask_anything': "En la sección /faq encontrarás los temas principales, pero **puedes preguntarme directamente lo que necesites** y te proporcionaré información y consejos.", # <-- Added
        'start_multilingual_info': "🌐 Puedo entender y responder en varios idiomas. Si prefieres otro idioma, simplemente escríbeme en él.",
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
        'plan_gold_desc': """*GOLD:*
- Uso avanzado y soporte prioritario
- {limit} mensajes/día
- Precio: {price}€/mes""", # <-- Añadido
        'plan_gold_name': "Gold", # <-- Añadido
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
        'upgrade_basic_desc': "💎 **Plan Basic ({basic_price}€/mes):**\n- {basic_limit} mensajes/día",
        'upgrade_premium_desc': "👑 **Plan Premium ({premium_price}€/mes):**\n- {premium_limit} mensajes/día",
        'upgrade_gold_desc': "🌟 **Plan Gold ({gold_price}€/mes):**\n- {gold_limit} mensajes/día", # <-- Añadido
        'upgrade_footer': "*Serás redirigido a Stripe para completar el pago seguro.*",
        'error_stripe_ids_missing': "Lo siento, la opción de mejora de plan no está configurada correctamente.",
        # Explain Conversation
        'processing_request': "🧠 Procesando tu solicitud... Por favor, espera un momento.", # <-- Añadido
        'consulting_knowledge_base': "Estoy consultando mis conocimientos y pensando en la mejor respuesta para ti 🧠. Un momento, por favor…", # <-- Mejorado v2
        'upgrade_desktop_copy_notice': "\n\n*Nota para usuarios de Escritorio:* Si el botón no abre el enlace directamente, por favor, copia la URL del botón (clic derecho > Copiar enlace) y pégala en tu navegador.", # <-- Añadido
        # Nombres de Planes
        'plan_free_name': "Gratuito",
        'plan_basic_name': "Básico",
        'plan_premium_name': "Premium",
        'plan_gold_name': "Gold", # <-- Añadido
        # Manage Subscription / Portal
        'manage_command_description': "/manage - Gestiona tu suscripción activa",
        'manage_no_subscription': "No parece que tengas una suscripción activa para gestionar. Puedes empezar una con /upgrade.",
        'manage_generating_portal': "Generando enlace a tu portal de gestión...",
        'manage_portal_link_message': "Haz clic aquí para gestionar tu suscripción (cancelar, actualizar pago, etc.):",
        'manage_portal_error': "Lo siento, hubo un error al generar el enlace a tu portal de gestión. Por favor, inténtalo de nuevo más tarde o contacta con soporte.",
        # Disclaimer
        'disclaimer_text': """⚠️ Aviso legal:

Este bot tiene fines exclusivamente informativos y educativos.

**No sustituye el diagnóstico, tratamiento o asesoramiento médico profesional.**

Si experimentas síntomas importantes o necesitas ayuda profesional, consulta a un profesional de la salud autorizado.

Al utilizar este bot, reconoces y aceptas estos términos.""",
        'start_disclaimer_info': "Usa /disclaimer para ver información importante sobre el uso del bot."
    },
    'en': {
        # FAQ Buttons
        'faq_understand_dpdr': "🧠 Understand DPDR",
        'faq_general_anxiety': "🌀 General Anxiety",
        'faq_symptoms': "🩺 Symptoms",
        'faq_exercises': "🧘 Exercises",
        'faq_explain_other': "🗣️ Explain to Others", # Emoji changed
        'faq_resources': "📚 Resources",
        # FAQ Descriptions (Keep as is)
        'faq_select_area': "Select an area of interest:",
        'faq_area_understand': "🧠 **Understand DPDR:** A reassuring explanation of what it is and why it happens.",
        'faq_area_anxiety': "🌀 **General Anxiety:** Information about anxiety, its mechanisms, and how it manifests.",
        'faq_area_explain': "❤️ **Explain to Others:** Help to describe your experience (DPDR or anxiety) to family and friends.",
        'faq_area_symptoms': "🩺 **Symptoms:** A review of common symptoms and what they might indicate.",
        'faq_area_exercises': "🧘 **Exercises:** Practical techniques and exercises to manage DPDR and anxiety.",
        'faq_area_resources': "📚 **Resources:** Links, books, and other support materials.",
         # Fixed FAQ Responses <-- NEW SECTION
        'faq_response_understand_dpdr': """🧩 **Understand DPDR:**

Depersonalization and derealization (DPDR) are unsettling but harmless experiences that many people go through, especially during periods of high emotional or psychological stress. They are defense mechanisms of the mind, designed to help you cope when stress becomes overwhelming.

*Depersonalization* is the feeling of being detached from yourself—like you're observing your thoughts, body, or actions from the outside. You may feel numb or robotic, as if you're not really \"in\" your body.

*Derealization*, on the other hand, is the sensation that the world around you is unreal—like you're in a dream or behind a glass wall. Things may look strange, distorted, or artificial.

Though these experiences are deeply uncomfortable, they're actually quite common among people with anxiety or after intense stress or trauma. They're not dangerous, they're not signs of "going crazy," and they don't mean there's anything permanently wrong with you. In fact, they're reversible once the body and mind begin to feel safe again.

Would you like a version that feels more personal or easier to relate to? (If so, just ask)""",
        'faq_response_general_anxiety': """🌪️ **General Anxiety:**

General anxiety is a constant feeling of worry, nervousness, or tension, even when there's no real or immediate danger. It's more than just "feeling stressed"—it can feel like something bad is about to happen, even if you don't know what exactly.

In the **body**, anxiety can show up as a racing heart, tight muscles, shortness of breath, chest discomfort, or trouble sleeping. This happens because the body goes into a "high alert" mode, like it's preparing to protect you from danger—even when there is none.

In the **mind**, anxiety can create repetitive or negative thoughts. You might find yourself stuck in a loop of "what ifs" like, "What if this never gets better?" or "What if something's wrong with me?" These thoughts can be exhausting and make you feel disconnected or overwhelmed.

Anxiety can become **persistent** because the body and brain start to get used to being in that alert state. Sometimes a stressful experience starts it, but even after the situation is over, your nervous system can keep acting like there's still something to fear. It's like the "alarm button" got stuck in the ON position.

The good news is: this state **can be changed**. You're not broken. With the right tools and support, your body and mind can return to a calmer, more balanced state.

Is there a specific part you'd like to know more about? (If so, just ask)""",
        'faq_response_symptoms': """🩺**Symptoms:**

Here's a list of the most common DPDR (depersonalization and derealization) and anxiety symptoms, grouped by type:

🧠 **Cognitive (Mental) Symptoms**
* Feeling disconnected from yourself (like you're observing your life from outside your body)
* Feeling like the world isn't real or looks "dreamlike," foggy, or artificial
* Racing thoughts or overthinking
* Difficulty concentrating or memory problems ("brain fog")
* Fear of "going crazy" or losing control
* Obsessive thinking about existence, reality, or the self
* Feeling confused or mentally distant
* thinking too much about your condition is also part of anxiety

💬 **Emotional Symptoms**
* Numbness or lack of emotions (feeling flat or "robotic")
* Constant fear or dread
* Feeling detached from loved ones
* Sense of hopelessness or sadness
* Irritability or emotional sensitivity
* Mood swings or emotional overwhelm

🧍‍♂️ **Physical Symptoms**
* Tight chest or trouble breathing
* Fast heartbeat or palpitations
* Tension in the neck, shoulders, or jaw
* Dizziness or lightheadedness
* Tingling or numbness in hands, face, or body
* Shakiness or feeling weak
* Stomach issues (nausea, bloating, cramps)
* Trouble sleeping or disturbed rest
* Sudden "jolts" or internal "shocks" when trying to relax
* Feeling unreal when looking in the mirror

If you tell me your symptoms, I can help you understand what they might mean.""",
        'faq_response_exercises': """🧘‍♂️ **Exercises:**

When you're feeling disconnected, anxious, or overwhelmed, your body and mind are often stuck in a "survival mode." Simple grounding and breathing exercises can gently signal to your nervous system that you're safe—helping you return to the present moment and reconnect with yourself and your surroundings. These tools don't fix everything instantly, but they can give you a sense of calm and control when things feel out of balance.

Aquí tienes algunos ejercicios que puedes probar:

🌿 **1. 5-4-3-2-1 Grounding**
Name:
- **5 things you can see**
- **4 things you can touch**
- **3 things you can hear**
- **2 things you can smell**
- **1 thing you can taste**
This helps anchor your attention in the here and now.

🌬️ **2. Box Breathing**
Breathe in for **4 seconds**,
Hold for **4 seconds**,
Breathe out for **4 seconds**,
Hold again for **4 seconds**.
Repeat a few times to calm the body and mind.

✋ **3. Touch + Breath**
Place one hand on your chest, the other on your belly.
Take slow breaths, noticing how your hands rise and fall.
This helps you reconnect with your body and feel more grounded.

Want me to suggest one based on how you're feeling? (If so, just ask)""",
        'faq_response_explain_other': """🗣️ **Explain to Others:**

"I'm going through something called depersonalization and derealization. Sometimes I feel like I'm outside of my body, or like the world around me doesn't feel real. I know it sounds strange, but it's not dangerous, and it doesn't mean I'm going crazy.

What's happening is that when we go through intense stress or anxiety, the brain can switch into a kind of 'emergency mode.' It's an automatic, deeply wired survival response called the **freeze response**.

This response comes from our ancestors. When an animal couldn't run or fight, its body would shut down or disconnect to protect itself from trauma. It's a defense mechanism.

In my case, even though there's no real danger, my nervous system still reacts like there is — and that's what causes these weird, disconnected feelings.

The good news is that this state isn't permanent. With time, support, and the right tools, the body and mind can return to feeling safe and present again.

What helps me the most is just feeling heard and supported, even if you don't fully understand it."

Want me to adjust it to match more closely how *you* experience it? I can help with that. (If so, just ask)

📚 **Resources:**

📚 **Books**
- *The Depersonalization Manual* – Shaun O'Connor
- *Overcoming Depersonalization Disorder* – Fugen Neziroglu & Katharine Donnelly
- *Feeling Unreal* – Daphne Simeon & Jeffrey Abugel
- *Stop Unreality* – Kevin Klix
- *The Body Keeps the Score* – Bessel van der Kolk (trauma-informed perspective)

🌐 **Websites & Online Resources**
- [**dpmanual.com**](https://www.dpmanual.com/) – Shaun O'Connor's recovery guide
- [**unrealuk.org**](https://www.unrealuk.org/) – UK charity focused on DPDR
- [**anxietycentre.com**](https://www.anxietycentre.com/) – In-depth anxiety education and tools
- [**NAMI.org**](https://www.nami.org/) – General mental health resources
- [**YouTube: Jordan Hardgrave**](https://www.youtube.com/@JordanHardgrave) – Trauma and anxiety education

💬 **Forums & Communities**
- [**Reddit: r/DPDR**](https://www.reddit.com/r/DPDR/) – Peer support and shared experiences
- [**No More DP**](https://www.nomoredp.com/) – Community and tools from a recovered DPDR sufferer
- **HealthUnlocked: Anxiety Support** – Discussion forums

🧘‍♂️ **Apps & Tools**
- **Insight Timer** – Guided meditations for grounding and anxiety
- **CBT Thought Diary** – Cognitive behavioral therapy journaling
- **MindShift CBT** – Coping tools for anxiety
- **DARE: Break Free from Anxiety** – Based on the DARE method

🗣️ *If you'd like any of these resources in a specific language, let me know and I'll help you find them.*""",
        'faq_response_resources': """📚**Resources:**

📚 **Books**
- *The Depersonalization Manual* – Shaun O'Connor
- *Overcoming Depersonalization Disorder* – Fugen Neziroglu & Katharine Donnelly
- *Feeling Unreal* – Daphne Simeon & Jeffrey Abugel
- *Stop Unreality* – Kevin Klix
- *The Body Keeps the Score* – Bessel van der Kolk (trauma-informed perspective)

🌐 **Websites & Online Resources**
- [**dpmanual.com**](https://www.dpmanual.com/) – Shaun O'Connor's recovery guide
- [**unrealuk.org**](https://www.unrealuk.org/) – UK charity focused on DPDR
- [**anxietycentre.com**](https://www.anxietycentre.com/) – In-depth anxiety education and tools
- [**NAMI.org**](https://www.nami.org/) – General mental health resources
- [**YouTube: Jordan Hardgrave**](https://www.youtube.com/@JordanHardgrave) – Trauma and anxiety education

💬 **Forums & Communities**
- [**Reddit: r/DPDR**](https://www.reddit.com/r/DPDR/) – Peer support and shared experiences
- [**No More DP**](https://www.nomoredp.com/) – Community and tools from a recovered DPDR sufferer
- **HealthUnlocked: Anxiety Support** – Discussion forums

🧘‍♂️ **Apps & Tools**
- **Insight Timer** – Guided meditations for grounding and anxiety
- **CBT Thought Diary** – Cognitive behavioral therapy journaling
- **MindShift CBT** – Coping tools for anxiety
- **DARE: Break Free from Anxiety** – Based on the DARE method

🗣️ *If you'd like any of these resources in a specific language, let me know and I'll help you find them.*""",
        'faq_back_button': "⬅️ Back to FAQ Menu",
        # Feedback
        'feedback_useful': "👍 Useful",
        'feedback_not_useful': "👎 Not Useful",
        'feedback_prompt': "Was this answer helpful to you?",
        'feedback_thanks_positive': "Thanks for your positive feedback! 👍",
        'feedback_thanks_negative': "Thanks for your feedback. We'll take it into account to improve. 👍",
        'feedback_thanks_generic': "Thanks for your feedback.",
        # Commands
        'start_welcome_1': "Hi! I'm a guide specializing in anxiety and especially in its DPDR symptoms (depersonalization and derealization).",
        'start_welcome_2': "I can help you with information and advice based on specialized guides and resources.",
        'start_ask_anything': "In the /faq section you'll find the main topics, but **you can also ask me anything directly**, and I'll provide information and advice.", # <-- Added
        'start_multilingual_info': "🌐 I can understand and respond in multiple languages. If you prefer another language, just start writing in it.",
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
        'help_support': "/support - Contact support (if you need help)", # <-- Added missing key
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
        'plan_gold_name': "Gold", # <-- Añadido
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
        'upgrade_generating_link': "Generating secure payment link...", # <-- Added missing key
        'upgrade_basic_desc': "💎 **Basic Plan (€{basic_price}/month):**\n- {basic_limit} messages/day", # <-- Placeholder changed
        'upgrade_premium_desc': "👑 **Premium Plan (€{premium_price}/month):**\n- {premium_limit} messages/day", # <-- Placeholder changed
        'upgrade_gold_desc': "🌟 **Gold Plan (€{gold_price}/month):**\n- {gold_limit} messages/day", # <-- Añadido
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
        'consulting_knowledge_base': "I'm consulting my knowledge base and thinking about the best answer for you 🧠. One moment, please…", # <-- Mejorado v2
        'upgrade_desktop_copy_notice': "\n\n*Note for Desktop users:* If the button doesn't open the link directly, please copy the button's URL (right-click > Copy link) and paste it into your browser.", # <-- Added
        # Plan Names
        'plan_free_name': "Free",
        'plan_basic_name': "Basic",
        'plan_premium_name': "Premium",
        'plan_gold_name': "Gold", # <-- Añadido
        # Manage Subscription / Portal
        'manage_command_description': "/manage - Manage your active subscription",
        'manage_no_subscription': "It doesn't seem like you have an active subscription to manage. You can start one with /upgrade.",
        'manage_generating_portal': "Generating link to your management portal...",
        'manage_portal_link_message': "Click here to manage your subscription (cancel, update payment, etc.):",
        'manage_portal_error': "Sorry, there was an error generating the link to your management portal. Please try again later or contact support.",
        # Disclaimer
        'disclaimer_text': """⚠️ Disclaimer:

This bot is intended for informational and educational purposes only.

**It is not a substitute for professional diagnosis, treatment, or medical advice.**

If you are experiencing significant symptoms or require professional help, please consult a licensed healthcare provider.

By using this bot, you acknowledge and accept these terms.""",
        'start_disclaimer_info': "Use /disclaimer to view important information about the bot's usage."
    }
}

def get_text(key: str, lang_code: str | None = 'en', default: str | None = None, **kwargs) -> str:
    """Obtiene el texto traducido basado en el código de idioma y formatea con kwargs.
    Usa 'en' como fallback si el idioma o la clave no existen.
    Usa 'default' si la clave no se encuentra en ningún idioma.
    """
    # Determinar el idioma a usar, con fallback a 'en'
    lang = lang_code if lang_code in LOCALES else 'en'
    
    # Obtener la plantilla de texto para el idioma determinado
    # Si la clave no existe en ese idioma, intentar obtenerla de 'en'
    text_template = LOCALES.get(lang, {}).get(key)
    if text_template is None and lang != 'en':
        text_template = LOCALES.get('en', {}).get(key)
    
    # Si la clave no existe ni en el idioma solicitado ni en 'en', usar default o devolver clave
    if text_template is None:
        logging.warning(f"[get_text] Text key '{key}' not found in '{lang}' or 'en' locales. Using default.")
        text_template = default if default is not None else key
    
    # Formatear la plantilla con los argumentos proporcionados
    try:
        return text_template.format(**kwargs)
    except KeyError as e:
        logging.warning(f"[get_text] Missing format key '{e}' for text key '{key}' in lang '{lang}'")
        return text_template # Devuelve sin formatear si falta una clave de formato

# --- Fin i18n --- 

# --- Nueva Función Auxiliar Bilingüe ---
def create_bilingual_block(keys: list[str], join_char: str = "\n", separator: str = "\n\n---\n\n", **kwargs) -> str:
    """Crea un bloque de texto bilingüe (Inglés primero, luego Español).

    Args:
        keys: Lista de claves de texto (de LOCALES) a incluir.
        join_char: Caracter(es) para unir las líneas dentro de cada bloque de idioma.
        separator: Caracter(es) para separar el bloque inglés del español.
        **kwargs: Argumentos de formato a pasar a get_text.

    Returns:
        String con el bloque inglés, separador, y bloque español.
    """
    block_en_parts = []
    block_es_parts = []

    for key in keys:
        # Obtener texto para inglés, usando kwargs si existen
        text_en = get_text(key, 'en', **kwargs)
        block_en_parts.append(text_en)
        
        # Obtener texto para español, usando kwargs si existen
        text_es = get_text(key, 'es', **kwargs)
        block_es_parts.append(text_es)

    block_en = join_char.join(block_en_parts)
    block_es = join_char.join(block_es_parts)

    # Evitar separador si los bloques son idénticos (ej., si español no existe y fallback a inglés)
    if block_en == block_es:
        return block_en
    else:
        return f"{block_en}{separator}{block_es}"
# --- Fin Función Auxiliar ---

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
        "price": 4.99
    },
    "GOLD": {
        "name": "Plan Gold",
        "daily_messages": 50,
        "tokens_per_day": 25000, # Estimación, ajustar si es necesario
        "price": 9.99
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

        # Añadir columna stripe_customer_id si no existe
        try:
            c.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
            logging.info("Columna 'stripe_customer_id' añadida a la tabla 'users'.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e): raise e # Ignorar si ya existe

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

def update_user_stripe_customer_id(user_id: int, customer_id: str | None):
    """Actualiza o borra el stripe_customer_id de un usuario."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET stripe_customer_id = ? WHERE user_id = ?", (customer_id, user_id))
        conn.commit()
        logging.info(f"update_user_stripe_customer_id: Commit exitoso para user {user_id}") # <-- Log de commit
        logging.info(f"Stripe Customer ID actualizado para {user_id}: {'Borrado' if customer_id is None else customer_id}")
        return True
    except sqlite3.Error as e:
        logging.error(f"Error actualizando Stripe Customer ID para {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_by_customer_id(customer_id: str) -> sqlite3.Row | None:
    """Obtiene los datos de un usuario buscando por su Stripe Customer ID."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Buscar usuario por stripe_customer_id
        # Seleccionar las columnas que podríamos necesitar (al menos user_id)
        c.execute("SELECT user_id, plan, expiry_date FROM users WHERE stripe_customer_id = ?", (customer_id,))
        user_data = c.fetchone()
        if user_data:
             logging.info(f"Usuario encontrado para Customer ID {customer_id}: User ID {user_data['user_id']}")
        else:
             logging.warning(f"No se encontró usuario para Customer ID {customer_id}")
        return user_data # Devuelve Row o None
    except sqlite3.Error as e:
        logging.error(f"Error buscando usuario por Customer ID {customer_id}: {e}")
        return None
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

        # --- Saltar comprobación de límite para ADMINS ---
        is_admin = await is_user_admin(user_id) # <-- Usar nueva función async
        if not is_admin:
            # 1. Verificar límite de mensajes (solo si NO es admin)
            if daily_messages >= plan_limit:
                user_context['is_processing'] = False # Desbloquear
                plan_name = current_plan.capitalize() # TODO: Usar nombre de plan localizado?
                limit_msg_1 = get_text('limit_reached_1', lang)
                # Asegurarse de pasar los kwargs necesarios aquí
                limit_msg_2 = get_text('limit_reached_2', lang).format(plan_name=get_text(f'plan_{current_plan.lower()}_name', lang, default=plan_name), limit=plan_limit)
                limit_cta = get_text('limit_reached_cta', lang)
                full_limit_message = f"{limit_msg_1}\\n{limit_msg_2}\\n\\n{limit_cta}"
                if update.callback_query:
                    await update.callback_query.answer() # Responder primero al callback
                    await update.callback_query.message.reply_text(full_limit_message, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text(full_limit_message, parse_mode=ParseMode.MARKDOWN)
                return
        # Si es admin, el código continúa directamente aquí abajo sin verificar el límite

        # 2. Incrementar contador de mensajes (usando la función helper)
        # Se incrementa para todos, incluso admins, para estadísticas si se quiere
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
            # Comprobar si debemos usar el modelo más potente
            if CHECK_CRITICAL_KEYWORDS: 
                for keyword in CRITICAL_KEYWORDS:
                    if re.search(r'\b' + re.escape(keyword) + r'\b', message_text, re.IGNORECASE):
                        use_gpt4 = True
                        logging.warning(f"Palabra clave crítica detectada del usuario {user_id}. Usando GPT-4o.")
                        break

            # Definir el modelo a usar
            model_to_use = "gpt-4o" if use_gpt4 else "gpt-4o-mini"
            logging.info(f"Modelo OpenAI seleccionado para user {user_id}: {model_to_use}") # Log del modelo

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
                model=model_to_use 
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

    # --- Construcción del mensaje de /start con formato específico --- 
    # Bloque Inglés
    msg_en_welcome1 = get_text('start_welcome_1', 'en')
    msg_en_welcome2 = get_text('start_welcome_2', 'en')
    msg_en_ask_anything = get_text('start_ask_anything', 'en') # <-- Get new text
    msg_en_multilingual = get_text('start_multilingual_info', 'en')
    msg_en_commands_title = get_text('start_commands_title', 'en')
    msg_en_faq = get_text('start_faq', 'en')
    msg_en_plan = get_text('start_plan', 'en')
    msg_en_upgrade = get_text('start_upgrade', 'en')
    msg_en_reset = get_text('start_reset', 'en')
    msg_en_help = get_text('start_help', 'en')
    msg_en_manage = get_text('manage_command_description', 'en')
    msg_en_disclaimer = get_text('start_disclaimer_info', 'en')
    msg_en_cta = get_text('start_cta', 'en')

    block_en = (
        f"{msg_en_welcome1}\n"
        f"{msg_en_welcome2}\n\n"
        f"{msg_en_ask_anything}\n\n"  # <-- Add new text here
        f"{msg_en_multilingual}\n\n"
        f"{msg_en_commands_title}\n"
        f"{msg_en_faq}\n"
        f"{msg_en_plan}\n"
        f"{msg_en_upgrade}\n"
        f"{msg_en_reset}\n"
        f"{msg_en_help}\n"
        f"{msg_en_manage}\n\n"
        f"{msg_en_disclaimer}\n\n"
        f"{msg_en_cta}"
    )
    
    # Bloque Español
    msg_es_welcome1 = get_text('start_welcome_1', 'es')
    msg_es_welcome2 = get_text('start_welcome_2', 'es')
    msg_es_ask_anything = get_text('start_ask_anything', 'es') # <-- Get new text
    msg_es_multilingual = get_text('start_multilingual_info', 'es')
    msg_es_commands_title = get_text('start_commands_title', 'es')
    msg_es_faq = get_text('start_faq', 'es')
    msg_es_plan = get_text('start_plan', 'es')
    msg_es_upgrade = get_text('start_upgrade', 'es')
    msg_es_reset = get_text('start_reset', 'es')
    msg_es_help = get_text('start_help', 'es')
    msg_es_manage = get_text('manage_command_description', 'es')
    msg_es_disclaimer = get_text('start_disclaimer_info', 'es')
    msg_es_cta = get_text('start_cta', 'es')

    block_es = (
        f"{msg_es_welcome1}\n"
        f"{msg_es_welcome2}\n\n"
        f"{msg_es_ask_anything}\n\n"  # <-- Add new text here
        f"{msg_es_multilingual}\n\n"
        f"{msg_es_commands_title}\n"
        f"{msg_es_faq}\n"
        f"{msg_es_plan}\n"
        f"{msg_es_upgrade}\n"
        f"{msg_es_reset}\n"
        f"{msg_es_help}\n"
        f"{msg_es_manage}\n\n"
        f"{msg_es_disclaimer}\n\n"
        f"{msg_es_cta}"
    )

    # Combinar bloques
    if block_en == block_es:
        full_message = block_en
    else:
        full_message = f"{block_en}\n\n---\n\n{block_es}"
    # --- Fin Construcción --- 

    await update.message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    # Obtener lang de forma consistente
    lang = context.user_data.get(user_id, {}).get('lang', update.effective_user.language_code or 'en')
    message_text = update.message.text

    # --- Ignorar texto de botones de Feedback --- 
    feedback_useful_text = get_text('feedback_useful', lang)
    feedback_not_useful_text = get_text('feedback_not_useful', lang)
    if message_text == feedback_useful_text or message_text == feedback_not_useful_text:
        logging.info(f"Mensaje de texto ignorado (coincide con botón de feedback): '{message_text}' de {user_id}")
        return # No procesar estos textos
    # -------------------------------------------
    
    # --- Eliminar la lógica que interceptaba botones FAQ (ReplyKeyboard) ---
    # faq_keys = ['faq_understand_dpdr', 'faq_general_anxiety', 'faq_symptoms', 
    #             'faq_exercises', 'faq_explain_other', 'faq_resources']
    # is_faq_button = False
    # for key in faq_keys:
    #     # Comprobar si el texto coincide con CUALQUIERA de los idiomas del botón (podría ser problemático)
    #     if message_text == get_text(key, 'en') or message_text == get_text(key, 'es'):
    #         is_faq_button = True
    #         logging.warning(f"Texto de mensaje '{message_text}' de {user_id} coincide con botón FAQ (ReplyKeyboard?), será procesado por IA.")
    #         # En teoría, esto ya no debería pasar si solo usamos InlineKeyboard
    #         break
    # -------------------------------------------------------------------

    # Procesar cualquier otro texto normalmente llamando a la IA
    await process_user_input(user.id, lang, message_text, context, update)

    # Ya no necesitamos quitar el teclado aquí
    # if is_faq_button:
    #    await update.message.reply_text(get_text('faq_response_loading', lang, default="Procesando tu selección..."), 
    #                                 reply_markup=ReplyKeyboardRemove())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = user.language_code or 'en'
    logging.info(f"help_command: Ejecutado por user {user.id} (lang: {lang})") # <-- Log entrada

    # Definir las claves de texto para el mensaje de ayuda
    help_message_keys = [
        'help_title',
        'start_faq', # Reutilizamos claves de start si aplican
        'start_plan',
        'start_upgrade',
        'start_reset',
        'start_help',
        'manage_command_description', # <-- Añadir /manage
        'help_support', # Clave específica de help
        'start_disclaimer_info' # <-- Added /disclaimer info
        # 'help_cta' # Decidimos si incluir la llamada a la acción aquí o no
    ]

    # Construir el mensaje bilingüe
    help_text = create_bilingual_block(help_message_keys, join_char="\n", separator="\n\n---\n\n")
    
    # Añadir CTA opcional después (quizás no bilingüe o con su propia clave)
    cta_text = get_text('help_cta', lang) # Obtener CTA en el idioma del usuario
    # Descomentar para añadir CTA
    help_text += "\n\n" + cta_text
    
    logging.info(f"help_command: Texto generado (primeros 100 chars): {help_text[:100]}") # <-- Log texto

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
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'en') # Obtener idioma o default a 'en'
    user_data = get_user(user_id)

    if not user_data:
        await update.message.reply_text(get_text('error_no_user_data', lang))
        return

    # Ya no necesitamos las descripciones aquí si los botones tienen emojis
    # description_understand = get_text('faq_area_understand', lang)
    # description_anxiety = get_text('faq_area_anxiety', lang)
    # description_explain = get_text('faq_area_explain', lang)
    # description_symptoms = get_text('faq_area_symptoms', lang)
    # description_exercises = get_text('faq_area_exercises', lang)
    # description_resources = get_text('faq_area_resources', lang)

    keyboard = [
        [InlineKeyboardButton(get_text('faq_understand_dpdr', lang), callback_data='faq_understand_dpdr')],
        [InlineKeyboardButton(get_text('faq_general_anxiety', lang), callback_data='faq_general_anxiety')],
        [InlineKeyboardButton(get_text('faq_symptoms', lang), callback_data='faq_symptoms')],
        [InlineKeyboardButton(get_text('faq_exercises', lang), callback_data='faq_exercises')],
        [InlineKeyboardButton(get_text('faq_explain_other', lang), callback_data='faq_explain_other')],
        [InlineKeyboardButton(get_text('faq_resources', lang), callback_data='faq_resources')],
        # Consider adding a button for general help or asking a question directly?
        # [InlineKeyboardButton("❓ Ask my own question", callback_data='faq_ask_question')] # Example
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(get_text('faq_select_area', lang), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# --- Callback Query Handler for FAQ Buttons ---
async def faq_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Important to answer the callback query

    user_id = query.from_user.id
    # Obtener lang de context.user_data o default a 'en' si no está.
    # Esto es más robusto si el usuario cambia de idioma entre mensajes.
    lang = context.user_data.get(user_id, {}).get('lang', update.effective_user.language_code or 'en')
    callback_data = query.data

    # --- Mapeo de callback_data a claves de texto fijo ---
    fixed_responses = {
        'faq_understand_dpdr': 'faq_response_understand_dpdr',
        'faq_general_anxiety': 'faq_response_general_anxiety',
        'faq_symptoms': 'faq_response_symptoms',
        'faq_exercises': 'faq_response_exercises',
        'faq_explain_other': 'faq_response_explain_other',
        'faq_resources': 'faq_response_resources'
    }
    # -----------------------------------------------------

    if callback_data in fixed_responses:
        response_key = fixed_responses[callback_data]
        response_text = get_text(response_key, lang)
        # --- Añadir botón de Volver --- 
        keyboard = [
            [InlineKeyboardButton(get_text('faq_back_button', lang), callback_data='faq_back_to_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # -----------------------------
        # Usar edit_message_text para reemplazar el menú FAQ con la respuesta fija Y el botón
        await query.edit_message_text(
            text=response_text, 
            reply_markup=reply_markup, 
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True # <-- Added
        )
    
    elif callback_data == 'faq_back_to_menu':
        # --- Volver a mostrar el menú FAQ inicial --- 
        keyboard = [
            [InlineKeyboardButton(get_text('faq_understand_dpdr', lang), callback_data='faq_understand_dpdr')],
            [InlineKeyboardButton(get_text('faq_general_anxiety', lang), callback_data='faq_general_anxiety')],
            [InlineKeyboardButton(get_text('faq_symptoms', lang), callback_data='faq_symptoms')],
            [InlineKeyboardButton(get_text('faq_exercises', lang), callback_data='faq_exercises')],
            [InlineKeyboardButton(get_text('faq_explain_other', lang), callback_data='faq_explain_other')],
            [InlineKeyboardButton(get_text('faq_resources', lang), callback_data='faq_resources')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(get_text('faq_select_area', lang), reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        # ---------------------------------------------

    else:
        # Si no es una respuesta fija ni el botón de volver, procesar como pregunta a la IA
        button_text_key = callback_data 
        question_text = get_text(button_text_key, lang).split(' ', 1)[1] # Quita emoji

        if question_text: 
            processing_message = get_text('consulting_knowledge_base', lang)
            # Editamos el mensaje original para indicar que se está procesando
            await query.edit_message_text(text=processing_message, parse_mode=ParseMode.MARKDOWN)
            # Llamamos a process_user_input. Este se encargará de enviar la respuesta final.
            # Es importante pasar 'update' para que process_user_input sepa si viene de un callback.
            await process_user_input(user_id, lang, question_text, context, update)
        else:
            await query.edit_message_text(text=get_text('error_processing_selection', lang))

async def upgrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra opciones para actualizar el plan con botones inline."""
    # --- Nueva obtención de idioma ---
    user = update.effective_user
    lang = user.language_code or 'en'
    # ---------------------------------

    # --- Usar constantes para los Price IDs --- 
    basic_price_id = os.getenv('STRIPE_PRICE_ID_BASIC')
    premium_price_id = os.getenv('STRIPE_PRICE_ID_PREMIUM')
    gold_price_id = os.getenv('STRIPE_PRICE_ID_GOLD') # <-- Leer nuevo ID
    # ----------------------------------------

    # Verificar que todos los IDs necesarios existen
    if not basic_price_id or not premium_price_id or not gold_price_id:
        error_msg = create_bilingual_block(['error_stripe_ids_missing'])
        await update.message.reply_text(error_msg)
        logging.error("IDs de precios de Stripe (BASIC, PREMIUM o GOLD) no configurados en variables de entorno.")
        return

    # --- Obtener precios y límites desde SUBSCRIPTION_PLANS --- 
    basic_plan = SUBSCRIPTION_PLANS.get('BASIC', {})
    premium_plan = SUBSCRIPTION_PLANS.get('PREMIUM', {})
    gold_plan = SUBSCRIPTION_PLANS.get('GOLD', {}) # <-- Obtener datos Gold
    basic_price = basic_plan.get('price', 'N/A')
    premium_price = premium_plan.get('price', 'N/A')
    gold_price = gold_plan.get('price', 'N/A') # <-- Obtener precio Gold
    basic_limit = basic_plan.get('daily_messages', 'N/A')
    premium_limit = premium_plan.get('daily_messages', 'N/A')
    gold_limit = gold_plan.get('daily_messages', 'N/A') # <-- Obtener límite Gold
    # ------------------------------------------------------
    
    # --- Botones Inline (texto bilingüe manual) ---
    keyboard = [
        [
            InlineKeyboardButton(f"💎 Basic ({basic_price}€/mes) / Basic (€{basic_price}/month)", callback_data=f"upgrade_basic_{basic_price_id}"),
        ],
        [
            InlineKeyboardButton(f"👑 Premium ({premium_price}€/mes) / Premium (€{premium_price}/month)", callback_data=f"upgrade_premium_{premium_price_id}"),
        ],
        [
            InlineKeyboardButton(f"🌟 Gold ({gold_price}€/mes) / Gold (€{gold_price}/month)", callback_data=f"upgrade_gold_{gold_price_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # --------------------------------------------

    # --- Construir Texto Descriptivo Bilingüe --- 
    upgrade_text_keys = [
        'upgrade_title',
        'upgrade_basic_desc',
        'upgrade_premium_desc',
        'upgrade_gold_desc', # <-- Añadido
        'upgrade_footer'
    ]
    
    # Pasar precios y límites como kwargs para formatear dentro de create_bilingual_block
    format_args = {
        'basic_price': basic_price,
        'basic_limit': basic_limit,
        'premium_price': premium_price,
        'premium_limit': premium_limit,
        'gold_price': gold_price,
        'gold_limit': gold_limit
    }
    
    message_text = create_bilingual_block(upgrade_text_keys, 
                                          join_char="\n\n", # Doble salto de línea entre descripciones
                                          separator="\n\n---\n\n", 
                                          **format_args)
    # -------------------------------------------

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
    logging.info("upgrade_button_handler: Intentando editar mensaje a estado 'Generando...'") # <-- Log ANTES
    try:
        await query.edit_message_text(progress_text)
        logging.info("upgrade_button_handler: Mensaje editado OK.") # <-- Log DESPUÉS (éxito)
    except Exception as edit_e:
        logging.error(f"upgrade_button_handler: ERROR al editar mensaje de progreso: {edit_e}", exc_info=True) # <-- Log DESPUÉS (error)
        # Decidimos si continuar o no. Por ahora, continuamos.

    try:
        # --- Construir URLs para Stripe --- 
        constructed_success_url = YOUR_DOMAIN + '/stripe-success?session_id={CHECKOUT_SESSION_ID}' # <-- Corregido
        constructed_cancel_url = YOUR_DOMAIN + '/stripe-cancel' # <-- Corregido
        logging.info(f"upgrade_button_handler: Construyendo URLs para Stripe: success='{constructed_success_url}', cancel='{constructed_cancel_url}'")
        # -------------------------------------------
        logging.info(f"upgrade_button_handler: Intentando crear sesión de Stripe con Price ID: {price_id}")
        
        # --- Construir Mensaje Bilingüe --- 
        # Usamos create_bilingual_block para ambos textos
        payment_link_es = get_text('upgrade_payment_link_message', 'es', default="Haz clic aquí para completar tu suscripción:")
        notice_es = get_text('upgrade_desktop_copy_notice', 'es', default="\n\n*Nota para usuarios de Escritorio:* Si el botón no abre el enlace directamente, por favor, copia la URL del botón (clic derecho > Copiar enlace) y pégala en tu navegador.")
        message_es = f"{payment_link_es}{notice_es}"
        
        payment_link_en = get_text('upgrade_payment_link_message', 'en', default="Click here to complete your subscription:")
        notice_en = get_text('upgrade_desktop_copy_notice', 'en', default="\n\n*Note for Desktop users:* If the button doesn't open the link directly, please copy the button's URL (right-click > Copy link) and paste it into your browser.")
        message_en = f"{payment_link_en}{notice_en}"
        
        # Combinar ES y EN con separador
        if message_es != message_en: # Solo añadir separador si son diferentes
            full_message_text = f"{message_es}\n\n---\n\n{message_en}"
        else:
            full_message_text = message_es # O message_en, son iguales
        # ------------------------------------------

        # --- Configurar timeout para Stripe --- 
        stripe.timeout = 30 # 30 segundos de timeout
        # --------------------------------------
        
        # <<< Log Detallado Antes de Llamar a Stripe >>>
        logging.info(f"upgrade_button_handler: Llamando a stripe.checkout.Session.create con:")
        logging.info(f"  line_items: [{{'price': '{price_id}', 'quantity': 1}}] ")
        logging.info(f"  mode: 'subscription'")
        logging.info(f"  success_url: '{constructed_success_url}'")
        logging.info(f"  cancel_url: '{constructed_cancel_url}'")
        logging.info(f"  metadata: {{'telegram_user_id': '{str(user_id)}'}}")
        logging.info(f"  client_reference_id: '{str(user_id)}'") # <-- Log añadido
        # <<< Fin Log Detallado >>>

        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=constructed_success_url, # Usar variable corregida
            cancel_url=constructed_cancel_url,   # Usar variable corregida
            # customer_email=None, # Comentado como antes
            client_reference_id=str(user_id), # <-- AÑADIDO PARÁMETRO FALTANTE
            metadata={
                'telegram_user_id': str(user_id)
            }
            # request_options={ 'timeout': 30 } # Otra forma de pasar timeout específico
        )
        # --- Log URL de sesión devuelta --- 
        session_url = checkout_session.url
        logging.info(f"upgrade_button_handler: Sesión de Stripe creada: {checkout_session.id}. URL: {session_url}")
        # ----------------------------------

        # Asegurarse de que session_url no es None antes de usarlo
        if session_url:
            # --- Enviar enlace como Botón Inline --- 
            keyboard = [[InlineKeyboardButton("➡️ Pagar Ahora en Stripe / Pay Now on Stripe", url=session_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(full_message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN) # <-- Usar texto combinado
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
        # Si no hay datos, intentar enviar mensaje bilingüe
        error_msg = create_bilingual_block(['error_no_user_data'])
        await update.message.reply_text(error_msg)
        return

    # --- Calcular Datos Dinámicos ---
    current_plan = user_data['plan']
    daily_messages = user_data['daily_messages']
    expiry_date_str = user_data['expiry_date']
    plan_name_key = f'plan_{current_plan.lower()}_name' # Crear clave dinámica para nombre plan si existe
    plan_name_en = get_text(plan_name_key, 'en', default=current_plan.capitalize())
    plan_name_es = get_text(plan_name_key, 'es', default=current_plan.capitalize())
    
    plan_limit = SUBSCRIPTION_PLANS.get(current_plan.upper(), {}).get('daily_messages', 0)

    expiry_date_formatted_en = "N/A"
    expiry_date_formatted_es = "N/D"
    if expiry_date_str and current_plan.upper() != 'FREE':
        try:
            # Usar formato consistente ISO y luego formatear para cada idioma si es necesario
            expiry_date = datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00')) 
            expiry_date_formatted_en = expiry_date.strftime('%Y-%m-%d') # Formato EN/ISO
            expiry_date_formatted_es = expiry_date.strftime('%d-%m-%Y') # Formato ES
        except ValueError:
            logging.error(f"Error al parsear la fecha de expiración '{expiry_date_str}' para el usuario {user_id}")
            expiry_date_formatted_en = get_text('plan_expiry_error', 'en', default="Invalid date")
            expiry_date_formatted_es = get_text('plan_expiry_error', 'es', default="Fecha inválida")
            
    # Obtener precios y límites para todos los planes
    free_limit = SUBSCRIPTION_PLANS.get('FREE', {}).get('daily_messages', 0)
    basic_limit = SUBSCRIPTION_PLANS.get('BASIC', {}).get('daily_messages', 0)
    premium_limit = SUBSCRIPTION_PLANS.get('PREMIUM', {}).get('daily_messages', 0)
    gold_limit = SUBSCRIPTION_PLANS.get('GOLD', {}).get('daily_messages', 0) # <-- Obtener límite Gold
    basic_price = SUBSCRIPTION_PLANS.get('BASIC', {}).get('price', 'N/A')
    premium_price = SUBSCRIPTION_PLANS.get('PREMIUM', {}).get('price', 'N/A')
    gold_price = SUBSCRIPTION_PLANS.get('GOLD', {}).get('price', 'N/A') # <-- Obtener precio Gold
    # --------------------------------

    # --- Construir Bloque Inglés ---
    plan_info_expires_en = ""
    if current_plan.upper() != 'FREE':
        # Pasar expiry_date al formatear
        plan_info_expires_en = get_text('plan_expires', 'en', default="📅 Your subscription expires on: {expiry_date}").format(expiry_date=expiry_date_formatted_en)

    block_en = (
        f"{get_text('plan_title', 'en', default='📊 Your current plan:')}\n"
        f"**{plan_name_en}**\n" 
        f"{get_text('plan_messages_today', 'en', default='✉️ Messages used today:')} {daily_messages}/{plan_limit}\n"
        f"{plan_info_expires_en}\n\n"
        f"{get_text('plan_available_title', 'en', default='💡 Available plans')}\n"
        # Pasar limit y price al formatear
        f"{get_text('plan_free_desc', 'en', default='*FREE:*\n- Basic free plan\n- {limit} messages/day').format(limit=free_limit)}\n"
        f"{get_text('plan_basic_desc', 'en', default='*BASIC:*\n- For regular use\n- {limit} messages/day\n- Price: €{price}/month').format(limit=basic_limit, price=basic_price)}\n"
        f"{get_text('plan_premium_desc', 'en', default='*PREMIUM:*\n- For heavy use\n- {limit} messages/day\n- Price: €{price}/month').format(limit=premium_limit, price=premium_price)}\n"
        f"{get_text('plan_gold_desc', 'en', default='*GOLD:*\n- Advanced use and priority support\n- {limit} messages/day\n- Price: €{price}/month').format(limit=gold_limit, price=gold_price)}" # <-- Añadido Gold
    )
    # --------------------------------
    
    # --- Construir Bloque Español ---
    plan_info_expires_es = ""
    if current_plan.upper() != 'FREE':
        # Pasar expiry_date al formatear
        plan_info_expires_es = get_text('plan_expires', 'es', default='📅 Tu suscripción vence el: {expiry_date}').format(expiry_date=expiry_date_formatted_es)

    block_es = (
        f"{get_text('plan_title', 'es', default='📊 Tu plan actual:')}\n"
        f"**{plan_name_es}**\n"
        f"{get_text('plan_messages_today', 'es', default='✉️ Mensajes usados hoy:')} {daily_messages}/{plan_limit}\n"
        f"{plan_info_expires_es}\n\n"
        f"{get_text('plan_available_title', 'es', default='💡 Planes disponibles')}\n"
        # Pasar limit y price al formatear
        f"{get_text('plan_free_desc', 'es', default='*GRATUITO:*\n- Plan básico gratuito\n- {limit} mensajes/día').format(limit=free_limit)}\n"
        f"{get_text('plan_basic_desc', 'es', default='*BÁSICO:*\n- Para uso regular\n- {limit} mensajes/día\n- Precio: {price}€/mes').format(limit=basic_limit, price=basic_price)}\n"
        f"{get_text('plan_premium_desc', 'es', default='*PREMIUM:*\n- Para uso intensivo\n- {limit} mensajes/día\n- Precio: {price}€/mes').format(limit=premium_limit, price=premium_price)}\n"
        f"{get_text('plan_gold_desc', 'es', default='*GOLD:*\n- Uso avanzado y soporte prioritario\n- {limit} mensajes/día\n- Precio: {price}€/mes').format(limit=gold_limit, price=gold_price)}" # <-- Añadido Gold
    )
    # --------------------------------
    
    # --- Construir CTA Bilingüe ---
    cta_key = 'plan_upgrade_cta_free' if current_plan.upper() == 'FREE' else 'plan_upgrade_cta_paid'
    cta_bilingual = create_bilingual_block([cta_key], separator="\n") # Separador simple para CTA
    # --------------------------------

    # --- Combinar Todo ---
    separator = "\n\n---\n\n"
    full_message = f"{block_en}{separator}{block_es}\n\n{cta_bilingual}" 
    # --------------------------------

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

# --- Comando Temporal Admin: Fijar Customer ID ---
async def admin_set_customer_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Establece manualmente el Stripe Customer ID para un usuario."""
    admin_id = update.effective_user.id

    # 1. Verificar si es admin
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    # 2. Parsear y validar argumentos (user_id, customer_id)
    if len(context.args) != 2:
        await update.message.reply_text("⚠️ Uso: /set_customer_id <user_id> <stripe_customer_id>")
        return

    try:
        target_user_id = int(context.args[0])
        target_customer_id = context.args[1]
        if not target_customer_id.startswith("cus_"):
             await update.message.reply_text("⚠️ El ID de cliente debe empezar por 'cus_'.")
             return
    except ValueError:
        await update.message.reply_text("❌ Error: <user_id> debe ser un número.")
        return

    # 3. Actualizar base de datos usando la función existente
    logging.info(f"admin_set_customer_id: Intentando actualizar BD para user {target_user_id} con CustomerID {target_customer_id}") # <-- Log ANTES
    success = update_user_stripe_customer_id(target_user_id, target_customer_id)
    logging.info(f"admin_set_customer_id: Resultado de update_user_stripe_customer_id: {success}") # <-- Log DESPUÉS

    # 4. Confirmar al admin
    if success:
        await update.message.reply_text(f"✅ Stripe Customer ID actualizado para `{target_user_id}`: `{target_customer_id}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Error al actualizar el Customer ID para `{target_user_id}`.")

# --- Fin Comando Temporal ---

# --- Nuevos Comandos Gestión Admin (DEFINICIONES AÑADIDAS) ---
async def list_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Lista los usuarios marcados como administradores en la BD."""
    admin_id = update.effective_user.id
    if not await is_user_admin(admin_id):
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Seleccionar usuarios donde is_admin es 1
        cursor.execute("SELECT user_id, username, first_name FROM users WHERE is_admin = 1 ORDER BY user_id")
        admins = cursor.fetchall()
        
        if not admins:
            await update.message.reply_text("ℹ️ No hay administradores configurados en la base de datos.")
            return

        message = f"👑 **Administradores Actuales ({len(admins)}):**\\n---\\n" 
        for admin in admins:
             user_info = f"👤 `{admin['user_id']}`" 
             if admin['username']:
                 user_info += f" (@{admin['username']})"
             elif admin['first_name']:
                  user_info += f" ({admin['first_name']})"
             message += user_info + "\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    except sqlite3.Error as e:
        logging.error(f"Error listando admins: {e}")
        await update.message.reply_text("❌ Error al consultar la lista de administradores.")
    finally:
        if conn:
            conn.close()

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Añade un usuario como administrador."""
    admin_id = update.effective_user.id
    if not await is_user_admin(admin_id):
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Uso: /add_admin <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Error: <user_id> debe ser un número.")
        return

    success = await set_admin_status(target_user_id, True)
    
    if success:
        await update.message.reply_text(f"✅ Usuario `{target_user_id}` establecido como administrador.", parse_mode='Markdown')
    else:
        # set_admin_status ya loguea el error, aquí damos mensaje genérico o más info
        await update.message.reply_text(f"❌ No se pudo establecer como admin a `{target_user_id}`. Verifica que el usuario existe.", parse_mode='Markdown')

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[ADMIN] Remueve a un usuario de ser administrador."""
    admin_id = update.effective_user.id
    if not await is_user_admin(admin_id):
        await update.message.reply_text("⛔ No tienes permiso para usar este comando.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Uso: /remove_admin <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Error: <user_id> debe ser un número.")
        return
        
    # Evitar que el admin inicial se quite a sí mismo accidentalmente?
    # Podríamos añadir: if target_user_id == 23684095: ... return
    # O confiar en que el admin sabe lo que hace.

    success = await set_admin_status(target_user_id, False)
    
    if success:
        await update.message.reply_text(f"✅ Usuario `{target_user_id}` ya no es administrador.", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ No se pudo quitar como admin a `{target_user_id}`.", parse_mode='Markdown')

# --- Fin Nuevos Comandos Gestión Admin ---

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
        
        # Definir el modelo a usar
        model_to_use = "gpt-4o" if use_gpt4 else "gpt-4o-mini"
        logging.info(f"Modelo OpenAI seleccionado para explain {user_id}: {model_to_use}") # Log del modelo

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
            instructions=final_instructions, # <-- Asegurarse de pasarla
            model=model_to_use   # <---- ¡ASÍ! (Sin el #)
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
            await update.message.reply_text(full_response, disable_web_page_preview=True) # <-- Added

        else:
            logging.error(f"La ejecución de explicación falló para {user_id} con estado: {run.status}")
            error_text = get_text('error_openai_run', lang, default="Lo siento, no pude generar la explicación en este momento.")
            await update.message.reply_text(error_text, disable_web_page_preview=True) # <-- Added

    except Exception as e:
        logging.error(f"Error inesperado al generar explicación para {user_id}: {e}", exc_info=True)
        error_message = get_text('error_generic', lang).format(error=str(e))
        await update.message.reply_text(error_message, disable_web_page_preview=True) # <-- Added

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
        f"**Consulta:**\\n{support_query}"
    )

    # --- Enviar notificación SOLO al admin principal (ID fijo) ---
    TARGET_ADMIN_ID = 23684095
    try:
        await context.bot.send_message(chat_id=TARGET_ADMIN_ID, text=notification_message, parse_mode=ParseMode.MARKDOWN)
        logging.info(f"Notificación de soporte enviada al admin principal {TARGET_ADMIN_ID}")
    except Exception as e:
        logging.error(f"Error enviando notificación de soporte al admin principal {TARGET_ADMIN_ID}: {e}")
    # --- Fin envío a admin principal ---

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

# --- Fin Funciones Conversación ---

# --- Fin Funciones Admin ---

# --- Funciones para Gestión de Suscripción (Portal Stripe) ---
async def create_stripe_portal_session(customer_id: str) -> str | None:
    """Crea una sesión del Portal de Clientes de Stripe y devuelve la URL."""
    if not stripe.api_key:
        logging.error("Intento de crear sesión de portal de Stripe sin API key configurada.")
        return None
    
    # Aquí podrías definir una URL de retorno específica si no quieres usar la
    # configurada por defecto en el dashboard de Stripe.
    # return_url = YOUR_DOMAIN + '/portal-return' 
    
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            # return_url=return_url, # Descomentar si usas una URL de retorno específica
        )
        logging.info(f"Sesión de Stripe Portal creada para customer {customer_id}: {portal_session.id}")
        return portal_session.url
    except stripe.error.StripeError as e:
        logging.error(f"Error de Stripe API creando sesión de portal para customer {customer_id}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error inesperado creando sesión de portal para customer {customer_id}: {e}")
        return None

async def manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite al usuario gestionar su suscripción activa a través del Portal de Clientes de Stripe."""
    user = update.effective_user
    user_id = user.id
    lang = user.language_code or 'en'
    logging.info(f"manage_command: Ejecutado por user {user_id}")

    # 1. Obtener datos del usuario, incluyendo stripe_customer_id
    conn = None
    customer_id = None
    plan = 'FREE' # Asumir FREE por defecto
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Seleccionar la nueva columna
        cursor.execute("SELECT plan, stripe_customer_id FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            plan = user_data['plan']
            customer_id = user_data['stripe_customer_id']
            logging.info(f"manage_command: Datos encontrados - Plan: {plan}, CustomerID: {customer_id}")
        else:
            logging.warning(f"manage_command: Usuario {user_id} no encontrado en la BD.")
            await update.message.reply_text(create_bilingual_block(['manage_no_subscription']))
            return
    except sqlite3.Error as e:
        logging.error(f"manage_command: Error DB obteniendo datos para user {user_id}: {e}")
        await update.message.reply_text(create_bilingual_block(['error_generic']).format(error=str(e)))
        return
    finally:
        if conn:
            conn.close()

    # 2. Verificar si tiene suscripción activa (Plan != FREE y Customer ID existe)
    if plan.upper() == 'FREE' or not customer_id:
        logging.info(f"manage_command: Usuario {user_id} no tiene suscripción activa o customer ID.")
        await update.message.reply_text(create_bilingual_block(['manage_no_subscription']))
        return

    # 3. Generar enlace al portal
    await update.message.reply_text(create_bilingual_block(['manage_generating_portal']))
    portal_url = await create_stripe_portal_session(customer_id)

    # 4. Enviar enlace o mensaje de error
    if portal_url:
        # --- Construir mensaje bilingüe manualmente (ES / EN) ---
        link_message_es = get_text('manage_portal_link_message', 'es', default="Haz clic aquí para gestionar tu suscripción (cancelar, actualizar pago, etc.):")
        notice_es = get_text('upgrade_desktop_copy_notice', 'es', default="\n\n*Nota para usuarios de Escritorio:* Si el botón no abre el enlace directamente, por favor, copia la URL del botón (clic derecho > Copiar enlace) y pégala en tu navegador.")
        message_es = f"{link_message_es}{notice_es}"

        link_message_en = get_text('manage_portal_link_message', 'en', default="Click here to manage your subscription (cancel, update payment, etc.):")
        notice_en = get_text('upgrade_desktop_copy_notice', 'en', default="\n\n*Note for Desktop users:* If the button doesn't open the link directly, please copy the button's URL (right-click > Copy link) and paste it into your browser.")
        message_en = f"{link_message_en}{notice_en}"

        if message_es != message_en:
            full_message_text = f"{message_es}\n\n---\n\n{message_en}"
        else:
            full_message_text = message_es
        # ------------------------------------------------------

        keyboard = [[InlineKeyboardButton("➡️ Gestionar Suscripción / Manage Subscription", url=portal_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(full_message_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        logging.info(f"manage_command: Enlace al portal enviado a user {user_id}")
    else:
        logging.error(f"manage_command: No se pudo generar URL del portal para customer {customer_id}")
        await update.message.reply_text(create_bilingual_block(['manage_portal_error']))

# --- Fin Funciones Portal ---

# --- Funciones Auxiliares para Roles Admin (AÑADIDAS) ---
async def is_user_admin(user_id: int) -> bool:
    """Verifica si un usuario es administrador consultando la BD."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Asegurarse de que la columna is_admin existe y se consulta
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        # Devolver True si se encuentra el usuario y is_admin es 1
        is_admin = bool(result and result['is_admin'] == 1)
        # logging.debug(f"is_user_admin check for {user_id}: {is_admin}") # Log opcional
        return is_admin
    except sqlite3.Error as e:
        # Loguear si la columna no existe u otro error
        logging.error(f"Error verificando estado admin para {user_id} (puede que falte columna 'is_admin'): {e}")
        return False # Asumir no admin si hay error
    finally:
        if conn:
            conn.close()

async def set_admin_status(target_user_id: int, status: bool) -> bool:
    """Establece el estado de administrador (1 para True, 0 para False)."""
    conn = None
    admin_value = 1 if status else 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Verificar si el usuario existe primero
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (target_user_id,))
        user_exists = cursor.fetchone()
        if not user_exists:
            logging.warning(f"Intento de cambiar estado admin para usuario inexistente: {target_user_id}")
            return False # No se puede cambiar estado a usuario inexistente
            
        cursor.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (admin_value, target_user_id))
        conn.commit()
        logging.info(f"Estado admin actualizado para {target_user_id}: {status}")
        return True
    except sqlite3.Error as e:
        logging.error(f"Error actualizando estado admin para {target_user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()
# --- Fin Funciones Auxiliares Admin ---

async def disclaimer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el disclaimer del bot."""
    # Obtener textos para ambos idiomas
    text_en = get_text('disclaimer_text', 'en')
    text_es = get_text('disclaimer_text', 'es')
    
    # Construir mensaje bilingüe manualmente
    if text_en == text_es: # Fallback si español no existe
        disclaimer_bilingual_text = text_en
    else:
        disclaimer_bilingual_text = f"{text_en}\n\n---\n\n{text_es}"
        
    # Enviar con parse_mode=ParseMode.MARKDOWN
    await update.message.reply_text(disclaimer_bilingual_text, parse_mode=ParseMode.MARKDOWN)

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
        application.add_handler(CommandHandler("manage", manage_command))
        application.add_handler(CommandHandler("disclaimer", disclaimer_command)) # <-- Añadido handler /disclaimer
        
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
        # Asegurarse de que esta línea NO esté comentada
        application.add_handler(CallbackQueryHandler(faq_callback_handler, pattern='^faq_')) 
        # ---------------------------------------

        # Handler general de mensajes (al final)
        # (Debe ignorar el texto de los botones que inician conversaciones)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex('^Explicar a Otros$'), handle_message))

        # --- Añadir comandos de Admin ---
        application.add_handler(CommandHandler("user_info", admin_user_info_command))
        application.add_handler(CommandHandler("set_plan", admin_set_plan_command))
        application.add_handler(CommandHandler("view_feedback", admin_view_feedback_command))
        application.add_handler(CommandHandler("list_users", admin_list_users_command))
        application.add_handler(CommandHandler("set_customer_id", admin_set_customer_id_command))
        application.add_handler(CommandHandler("list_admins", list_admins_command))
        application.add_handler(CommandHandler("add_admin", add_admin_command))
        application.add_handler(CommandHandler("remove_admin", remove_admin_command))
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
    # El bloque "Actualización puntual (Reintento)" que estaba aquí se elimina.
    
    # Continuar con el inicio normal del bot
    main()

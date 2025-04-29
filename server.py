# server.py
import os
import logging
import sys
import json
import stripe
import httpx # <-- Añadir import
from datetime import datetime, timedelta, timezone # <-- Añadir datetime, timedelta, timezone
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# --- Importar desde bot.py ---
# Esto asume que bot.py está en el mismo directorio
# Puede ser frágil; refactorizar a un módulo compartido sería mejor a largo plazo
try:
    from bot import (
        update_user_plan,
        update_user_stripe_customer_id,
        get_user_by_customer_id,
        STRIPE_PRICE_ID_BASIC,
        STRIPE_PRICE_ID_PREMIUM,
        SUBSCRIPTION_PLANS # Necesario si quieres loguear el nombre del plan
    )
    logging.info("Funciones/constantes importadas correctamente desde bot.py")
except ImportError as e:
    logging.error(f"Error importando desde bot.py: {e}. El procesamiento de webhooks fallará.")
    # Definir stubs para evitar errores al iniciar si falla la importación
    def update_user_plan(user_id, plan, expiry): pass
    def update_user_stripe_customer_id(user_id, customer_id): pass
    def get_user_by_customer_id(customer_id): return None
    STRIPE_PRICE_ID_BASIC = None
    STRIPE_PRICE_ID_PREMIUM = None
    SUBSCRIPTION_PLANS = {}
# --- Fin Importar ---


# Cargar variables de entorno
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN') # <-- Necesitamos el token aquí
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY') # <-- Añadir para asegurar que stripe.api_key se establece

# Configurar la clave API de Stripe (necesaria para verificar webhooks si se usa la API)
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
     logging.warning("STRIPE_SECRET_KEY no encontrada. La verificación de webhooks y la API de Stripe podrían fallar.")


# Configurar logging básico para el servidor
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

# --- Verificación inicial del Webhook Secret y BOT_TOKEN ---
if not STRIPE_WEBHOOK_SECRET:
    logging.critical("¡ERROR CRÍTICO! STRIPE_WEBHOOK_SECRET no está configurado en las variables de entorno. "
                     "El webhook no funcionará de forma segura.")
    # Podrías decidir salir si es absolutamente esencial, aunque Flask seguirá corriendo.
    # sys.exit(1)
if not BOT_TOKEN:
    logging.critical("¡ERROR CRÍTICO! BOT_TOKEN no está configurado...")
# --- Fin Verificación ---

# Crear la aplicación Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Webhook server is running."

# --- Función auxiliar asíncrona para enviar mensaje ---
async def send_telegram_message(user_id: int, text: str):
    if not BOT_TOKEN:
        logging.error("[TelegramSend] No BOT_TOKEN available.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': user_id,
        'text': text,
        'parse_mode': 'Markdown' # Opcional: para formato
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            response.raise_for_status() # Lanza excepción si hay error HTTP (4xx o 5xx)
            logging.info(f"[TelegramSend] Mensaje de confirmación enviado a user {user_id}. Respuesta: {response.status_code}")
    except httpx.RequestError as exc:
        logging.error(f"[TelegramSend] Error de red/conexión enviando mensaje a user {user_id}: {exc}")
    except httpx.HTTPStatusError as exc:
        logging.error(f"[TelegramSend] Error HTTP enviando mensaje a user {user_id}: {exc.response.status_code} - {exc.response.text}")
    except Exception as e:
        logging.error(f"[TelegramSend] Error inesperado enviando mensaje a user {user_id}: {e}", exc_info=True)
# --- Fin Función auxiliar --- 

@app.route('/webhook/stripe', methods=['POST'])
async def stripe_webhook(): # <<< Hacer la función async >>>
    logging.info("[Webhook] Petición POST recibida en /webhook/stripe") # Log inicial
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    if not STRIPE_WEBHOOK_SECRET:
         logging.error("[Webhook] Falta STRIPE_WEBHOOK_SECRET, abortando.")
         abort(500, description="Webhook secret not configured") # Error interno del servidor con descripción
         # No necesitamos return aquí, abort ya corta la ejecución

    logging.info("[Webhook] Intentando verificar firma...")
    try:
        # Pasar la clave secreta directamente es más seguro
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        logging.info(f"[Webhook] Firma verificada OK. Event ID: {event.get('id')}, Type: {event.get('type')}")

    except ValueError as e:
        # Payload inválido
        logging.error(f"[Webhook] Error ValueError en construct_event (payload inválido): {e}")
        abort(400, description="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Firma inválida
        logging.error(f"[Webhook] Error SignatureVerificationError en construct_event (firma inválida): {e}")
        abort(400, description="Invalid signature")
    except Exception as e:
        # Otro error durante la verificación
        logging.error(f"[Webhook] Error GENÉRICO INESPERADO en construct_event: {e}", exc_info=True)
        abort(500, description="Webhook signature verification error")

    # --- Procesamiento de Eventos Verificados ---
    event_type = event.get('type')
    event_data = event.get('data', {}).get('object', {}) # Obtener el objeto del evento

    # --- Manejo de checkout.session.completed ---
    if event_type == 'checkout.session.completed':
        logging.info("[Webhook] Evento 'checkout.session.completed' detectado. Procesando...")
        session = event_data # El objeto del evento es la sesión
        session_id = session.get('id')
        logging.info(f"[Webhook] ID de sesión: {session_id}")

        # Extraer datos necesarios
        client_reference_id = session.get('client_reference_id') # Nuestro user_id
        subscription_id = session.get('subscription') # ID de la nueva suscripción
        payment_status = session.get('payment_status')
        stripe_customer_id = session.get('customer') # ID del cliente en Stripe

        logging.info(f"[Webhook] Datos extraídos: client_ref='{client_reference_id}', sub_id='{subscription_id}', payment_status='{payment_status}', customer_id='{stripe_customer_id}'")

        # Solo proceder si el pago fue exitoso y tenemos la información necesaria
        if payment_status == 'paid' and client_reference_id and subscription_id and stripe_customer_id:
            logging.info("[Webhook] Pago exitoso y datos completos. Actualizando base de datos...")
            try:
                user_id = int(client_reference_id)

                # 1. Guardar/Actualizar el Customer ID de Stripe para el usuario
                try:
                    if callable(update_user_stripe_customer_id):
                        update_user_stripe_customer_id(user_id, stripe_customer_id)
                        logging.info(f"[Webhook] Stripe Customer ID '{stripe_customer_id}' guardado para user {user_id}.")
                    else:
                         logging.error("[Webhook] ❌ update_user_stripe_customer_id no es callable.")
                except Exception as e_cust:
                    logging.error(f"[Webhook] ❌ Excepción al guardar Stripe Customer ID para user {user_id}: {e_cust}")
                    # Continuar igualmente para intentar actualizar el plan

                # 2. Obtener el Price ID de la suscripción para saber qué plan compró
                price_id = None
                try:
                    # Usar la clave API de Stripe configurada globalmente
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    # Acceder correctamente a los items de la suscripción
                    if subscription and subscription['items'] and subscription['items']['data']:
                        price_id = subscription['items']['data'][0]['price']['id']
                        logging.info(f"[Webhook] Subscription {subscription_id} recuperada. Price ID: {price_id}")
                    else:
                        logging.error(f"[Webhook] No se encontraron items o price ID en la suscripción {subscription_id} para user {user_id}")
                except stripe.error.StripeError as e_sub:
                    logging.error(f"[Webhook] Error de Stripe API obteniendo suscripción {subscription_id}: {e_sub}")
                except Exception as e_sub_gen:
                     logging.error(f"[Webhook] Error inesperado obteniendo suscripción {subscription_id}: {e_sub_gen}")

                # 3. Determinar el plan y la fecha de expiración
                target_plan = None
                if price_id:
                    if price_id == STRIPE_PRICE_ID_BASIC:
                        target_plan = 'BASIC'
                    elif price_id == STRIPE_PRICE_ID_PREMIUM:
                        target_plan = 'PREMIUM'
                    elif price_id == os.getenv('STRIPE_PRICE_ID_GOLD'): # Comprobar GOLD también
                         target_plan = 'GOLD'
                    else:
                        logging.warning(f"[Webhook] Price ID desconocido ({price_id}) recibido de Stripe para user {user_id}. No se actualizará el plan.")
                else:
                    logging.error(f"[Webhook] No se pudo obtener el Price ID de la suscripción {subscription_id}. No se actualizará el plan.")

                # 4. Actualizar el plan en la base de datos si se determinó uno
                if target_plan:
                    # Calcular expiración (e.g., 31 días desde ahora para cubrir el mes)
                    # Stripe maneja la fecha de fin del periodo actual, pero podemos poner una aquí como referencia
                    # Es mejor usar la fecha de fin del periodo actual de la suscripción si está disponible
                    current_period_end_timestamp = subscription.get('current_period_end')
                    if current_period_end_timestamp:
                         expiry_date = datetime.fromtimestamp(current_period_end_timestamp, timezone.utc)
                         expiry_date_iso = expiry_date.date().isoformat()
                         logging.info(f"[Webhook] Usando current_period_end de Stripe: {expiry_date_iso}")
                    else:
                         # Fallback a 31 días si no podemos obtener current_period_end
                         expiry_date = datetime.now(timezone.utc) + timedelta(days=31)
                         expiry_date_iso = expiry_date.date().isoformat()
                         logging.warning(f"[Webhook] No se encontró current_period_end, usando fallback de 31 días: {expiry_date_iso}")

                    logging.info(f"[Webhook] Actualizando BD: user={user_id}, plan={target_plan}, expira={expiry_date_iso}")
                    try:
                        if callable(update_user_plan):
                           success = update_user_plan(user_id, target_plan, expiry_date_iso)
                           if success:
                               logging.info(f"[Webhook] ✅ Plan actualizado a {target_plan} para user {user_id}.")
                               # Enviar mensaje de confirmación
                               plan_name = SUBSCRIPTION_PLANS.get(target_plan, {}).get('name', target_plan)
                               expiry_date_formatted = datetime.fromisoformat(expiry_date_iso).strftime('%d/%m/%Y')
                               confirmation_text = (
                                   f"¡Felicidades! 🎉 Tu suscripción al **{plan_name}** está activa.\n"
                                   f"Puedes usar sus beneficios hasta el **{expiry_date_formatted}**.\n\n"
                                   f"Usa /plan para ver los detalles."
                               )
                               # Ejecutar envío de forma asíncrona
                               await send_telegram_message(user_id, confirmation_text)
                           else:
                               logging.error(f"[Webhook] ❌ update_user_plan retornó fallo para user {user_id}.")
                        else:
                           logging.error("[Webhook] ❌ update_user_plan no es callable.")
                    except Exception as e_plan:
                        logging.error(f"[Webhook] ❌ Excepción al llamar a update_user_plan: {e_plan}")
                else:
                    logging.warning(f"[Webhook] No se determinó target_plan válido a partir del Price ID {price_id}. No se actualizó la BD.")

            except ValueError:
                logging.error(f"[Webhook] Error: client_reference_id '{client_reference_id}' no es un user_id numérico válido.")
            except Exception as e_proc:
                 logging.error(f"[Webhook] Error inesperado procesando la sesión {session_id} para client_ref {client_reference_id}: {e_proc}", exc_info=True)
        else:
             logging.warning(f"[Webhook] Evento 'checkout.session.completed' recibido pero payment_status no es 'paid' o faltan datos. Session ID: {session_id}, Status: {payment_status}")

    # --- Manejo de customer.subscription.deleted ---
    elif event_type == 'customer.subscription.deleted':
        logging.info("[Webhook] Evento 'customer.subscription.deleted' detectado. Procesando cancelación...")
        subscription = event_data # El objeto del evento es la suscripción cancelada
        customer_id = subscription.get('customer')
        subscription_id = subscription.get('id')
        
        logging.info(f"[Webhook] Cancelación recibida para customer '{customer_id}', sub_id '{subscription_id}'")

        if customer_id:
            # Buscar al usuario por su Customer ID de Stripe
            logging.info(f"[Webhook] Buscando usuario con Customer ID: {customer_id}")
            user_info = get_user_by_customer_id(customer_id) # Asume que esta función existe y funciona

            if user_info and callable(update_user_plan):
                user_id = user_info['user_id']
                logging.info(f"[Webhook] Usuario {user_id} encontrado. Cambiando plan a FREE.")
                try:
                    # Cambiar plan a FREE y quitar fecha de expiración
                    success = update_user_plan(user_id, 'FREE', None)
                    if success:
                        logging.info(f"[Webhook] ✅ Plan cambiado a FREE para user {user_id} por cancelación.")
                        # Enviar mensaje de notificación de cancelación al usuario
                        cancellation_text = (
                            "Tu suscripción ha sido cancelada. "
                            "Has vuelto al plan Gratuito.\n\n"
                            "Gracias por usar el servicio."
                        )
                        await send_telegram_message(user_id, cancellation_text)
                    else:
                        logging.error(f"[Webhook] ❌ update_user_plan falló al intentar cambiar a FREE para user {user_id}.")
                except Exception as e_cancel:
                     logging.error(f"[Webhook] ❌ Excepción al actualizar a FREE para user {user_id}: {e_cancel}")
            elif not user_info:
                 logging.warning(f"[Webhook] No se encontró usuario con Customer ID '{customer_id}' para procesar cancelación.")
            elif not callable(update_user_plan):
                 logging.error("[Webhook] ❌ update_user_plan no es callable. No se puede procesar cancelación.")
        else:
            logging.warning(f"[Webhook] Evento 'customer.subscription.deleted' sin customer_id. Sub ID: {subscription_id}")
            
    # --- Manejo de invoice.payment_failed (Opcional) ---
    elif event_type == 'invoice.payment_failed':
        logging.warning(f"[Webhook] Evento 'invoice.payment_failed' detectado.")
        invoice = event_data
        customer_id = invoice.get('customer')
        invoice_id = invoice.get('id')
        attempt_count = invoice.get('attempt_count')
        next_attempt_timestamp = invoice.get('next_payment_attempt')
        
        logging.warning(f"[Webhook] Fallo de pago de factura {invoice_id} para customer {customer_id}. Intento: {attempt_count}.")
        
        # Opcional: Enviar notificación al usuario si fallan varios intentos
        if customer_id and attempt_count and attempt_count >= 2: # Notificar a partir del 2º fallo
            user_info = get_user_by_customer_id(customer_id)
            if user_info:
                 user_id = user_info['user_id']
                 failure_text = f"⚠️ Hubo un problema al procesar el pago de tu suscripción (Intento {attempt_count}). Por favor, revisa tu método de pago."
                 if next_attempt_timestamp:
                      next_attempt_dt = datetime.fromtimestamp(next_attempt_timestamp, timezone.utc)
                      next_attempt_str = next_attempt_dt.strftime('%d/%m/%Y')
                      failure_text += f" Se intentará de nuevo alrededor del {next_attempt_str}."
                 await send_telegram_message(user_id, failure_text)

    # --- Manejo de invoice.payment_succeeded (para renovaciones) ---
    elif event_type == 'invoice.payment_succeeded':
        logging.info("[Webhook] Evento 'invoice.payment_succeeded' detectado. Procesando renovación...")
        invoice = event_data
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        billing_reason = invoice.get('billing_reason') # e.g., 'subscription_cycle'

        logging.info(f"[Webhook] Pago de factura exitoso para customer {customer_id}, sub {subscription_id}, razón: {billing_reason}")

        # Solo procesar si es una renovación y tenemos los IDs
        if billing_reason == 'subscription_cycle' and customer_id and subscription_id:
             # Buscar usuario por customer_id
             user_info = get_user_by_customer_id(customer_id)
             if user_info and callable(update_user_plan):
                  user_id = user_info['user_id']
                  # Obtener la nueva fecha de fin del periodo de la suscripción
                  try:
                      subscription = stripe.Subscription.retrieve(subscription_id)
                      current_period_end_timestamp = subscription.get('current_period_end')
                      if current_period_end_timestamp:
                          new_expiry_date = datetime.fromtimestamp(current_period_end_timestamp, timezone.utc)
                          new_expiry_date_iso = new_expiry_date.date().isoformat()
                          current_plan = user_info.get('plan', 'UNKNOWN') # Usar plan actual de la BD
                          
                          # Actualizar solo la fecha de expiración del plan existente
                          success = update_user_plan(user_id, current_plan, new_expiry_date_iso)
                          if success:
                              logging.info(f"[Webhook] ✅ Fecha de expiración actualizada para user {user_id} (Plan {current_plan}) a {new_expiry_date_iso} por renovación.")
                              # Opcional: Enviar notificación de renovación exitosa
                              # renewal_text = f"¡Tu suscripción {current_plan} ha sido renovada exitosamente hasta el {new_expiry_date.strftime('%d/%m/%Y')}!"
                              # await send_telegram_message(user_id, renewal_text)
                          else:
                              logging.error(f"[Webhook] ❌ update_user_plan falló al actualizar fecha de expiración para user {user_id}.")
                      else:
                          logging.warning(f"[Webhook] No se encontró current_period_end en suscripción {subscription_id} durante renovación.")
                  except stripe.error.StripeError as e_sub:
                      logging.error(f"[Webhook] Error Stripe obteniendo suscripción {subscription_id} en renovación: {e_sub}")
                  except Exception as e_ren:
                      logging.error(f"[Webhook] ❌ Error procesando renovación para user {user_id}: {e_ren}")
             elif not user_info:
                  logging.warning(f"[Webhook] Usuario no encontrado para customer {customer_id} durante renovación.")
             elif not callable(update_user_plan):
                  logging.error("[Webhook] ❌ update_user_plan no es callable. No se puede procesar renovación.")
        else:
             logging.info(f"[Webhook] Evento 'invoice.payment_succeeded' ignorado (razón: {billing_reason}, customer: {customer_id}, sub: {subscription_id})")
             
    else:
        logging.info(f"[Webhook] Evento no manejado recibido: {event_type}")

    # Responder a Stripe para confirmar recepción
    return jsonify({'status': 'received'}), 200


@app.route('/stripe-success')
def stripe_success():
    # Podrías pasar el session_id como parámetro si quisieras personalizar el mensaje,
    # pero por ahora un mensaje genérico es suficiente.
    # session_id = request.args.get('session_id')
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pago Exitoso</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; text-align: center; padding: 40px; background-color: #f0fdf4; color: #14532d; }
            h1 { color: #16a34a; }
        </style>
    </head>
    <body>
        <h1>¡Pago Completado con Éxito!</h1>
        <p>Tu suscripción ha sido activada.</p>
        <p>Ya puedes cerrar esta ventana y volver a tu chat de Telegram.</p>
        <p>🎉</p>
    </body>
    </html>
    """

@app.route('/stripe-cancel')
def stripe_cancel():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pago Cancelado</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: sans-serif; text-align: center; padding: 40px; background-color: #fffbeb; color: #713f12; }
            h1 { color: #facc15; }
        </style>
    </head>
    <body>
        <h1>Pago Cancelado</h1>
        <p>Has cancelado el proceso de pago.</p>
        <p>Puedes cerrar esta ventana y volver a Telegram. Si cambias de opinión, puedes usar /upgrade de nuevo.</p>
        <p>😕</p>
    </body>
    </html>
    """
# --- Fin Rutas de Redirección ---

# --- Ejecutar el servidor ---
if __name__ == '__main__':
    # Obtener puerto de Railway o usar uno por defecto
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"Iniciando servidor Flask en el puerto {port}")
    # Ejecutar con un servidor WSGI de producción es mejor, pero esto funciona para Railway
    # waitress.serve(app, host='0.0.0.0', port=port) # Ejemplo con waitress
    app.run(host='0.0.0.0', port=port) # Usar el run de Flask por simplicidad aquí 
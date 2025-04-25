# server.py
import os
import logging
import sys
import json
import stripe # <-- Añadir import
from datetime import datetime, timedelta, timezone # <-- Añadir datetime, timedelta, timezone
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# --- Importar desde bot.py ---
# Esto asume que bot.py está en el mismo directorio
# Puede ser frágil; refactorizar a un módulo compartido sería mejor a largo plazo
try:
    from bot import (
        update_user_plan,
        STRIPE_PRICE_ID_BASIC,
        STRIPE_PRICE_ID_PREMIUM,
        SUBSCRIPTION_PLANS # Necesario si quieres loguear el nombre del plan
    )
    logging.info("Funciones/constantes importadas correctamente desde bot.py")
except ImportError as e:
    logging.error(f"Error importando desde bot.py: {e}. El procesamiento de webhooks fallará.")
    # Definir stubs para evitar errores al iniciar si falla la importación
    def update_user_plan(user_id, plan, expiry): pass
    STRIPE_PRICE_ID_BASIC = None
    STRIPE_PRICE_ID_PREMIUM = None
    SUBSCRIPTION_PLANS = {}
# --- Fin Importar ---


# Cargar variables de entorno
load_dotenv()
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
# Configurar la clave API de Stripe (necesaria para verificar webhooks si se usa la API)
# Stripe SDK usa STRIPE_SECRET_KEY automáticamente si está en env vars
if not os.getenv('STRIPE_SECRET_KEY'):
     logging.warning("STRIPE_SECRET_KEY no encontrada. La verificación de webhooks podría fallar si se usa la API.")


# Configurar logging básico para el servidor
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

# --- Verificación inicial del Webhook Secret ---
if not STRIPE_WEBHOOK_SECRET:
    logging.critical("¡ERROR CRÍTICO! STRIPE_WEBHOOK_SECRET no está configurado en las variables de entorno. "
                     "El webhook no funcionará de forma segura.")
    # Podrías decidir salir si es absolutamente esencial, aunque Flask seguirá corriendo.
    # sys.exit(1)
# --- Fin Verificación ---

# Crear la aplicación Flask
app = Flask(__name__)

@app.route('/')
def index():
    return "Webhook server is running."

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    logging.info("Webhook de Stripe recibido...")
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    if not STRIPE_WEBHOOK_SECRET:
         logging.error("Falta STRIPE_WEBHOOK_SECRET, no se puede verificar el webhook.")
         abort(500) # Error interno del servidor
         return '', 500

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        logging.info(f"Webhook verificado. Event ID: {event['id']}, Type: {event['type']}")

    except ValueError as e:
        # Payload inválido o secreto incorrecto
        logging.error(f"Webhook Error: Payload inválido o secreto - {e}")
        abort(400)
        return '', 400
    except stripe.error.SignatureVerificationError as e:
        # Firma inválida
        logging.error(f"Webhook Error: Fallo en verificación de firma - {e}")
        abort(400)
        return '', 400
    except Exception as e:
        logging.error(f"Webhook Error: Otro error en construct_event - {e}")
        abort(500)
        return '', 500

    # --- Procesar el evento checkout.session.completed ---
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        logging.info(f"Procesando checkout.session.completed: {session.get('id')}")

        # Extraer información relevante
        client_reference_id = session.get('client_reference_id')
        subscription_id = session.get('subscription') # Útil para futura gestión
        payment_status = session.get('payment_status')

        if payment_status == 'paid' and client_reference_id and subscription_id:
            try:
                user_id = int(client_reference_id)
                logging.info(f"Pago completado para user_id: {user_id}, Suscripción: {subscription_id}")

                # Obtener detalles de la suscripción para saber qué plan se compró
                # (Podríamos obtener el price_id directamente de session.line_items, pero puede ser más complejo si hay varios items)
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    price_id = subscription['items']['data'][0]['price']['id']
                    logging.info(f"Price ID de la suscripción: {price_id}")
                except Exception as e:
                    logging.error(f"Error obteniendo detalles de suscripción {subscription_id} para user {user_id}: {e}")
                    # Decidir cómo manejar esto: ¿abortar? ¿loguear y continuar? Por ahora logueamos.
                    price_id = None # No podemos determinar el plan

                target_plan = None
                expiry_date_iso = None

                if price_id == STRIPE_PRICE_ID_BASIC:
                    target_plan = 'BASIC'
                elif price_id == STRIPE_PRICE_ID_PREMIUM:
                    target_plan = 'PREMIUM'
                else:
                    logging.warning(f"Price ID desconocido ({price_id}) en webhook para user {user_id}. No se actualizará el plan.")

                if target_plan:
                    # Calcular fecha de expiración (ej: 30 días desde ahora)
                    # Usar timezone.utc para evitar problemas con zonas horarias
                    expiry_date = datetime.now(timezone.utc) + timedelta(days=30)
                    expiry_date_iso = expiry_date.date().isoformat() # Guardar solo fecha
                    logging.info(f"Plan a actualizar: {target_plan}, Expiración calculada: {expiry_date_iso}")

                    # Actualizar base de datos
                    try:
                        # Asegurarse de que la función importada está disponible
                        if callable(update_user_plan):
                           success = update_user_plan(user_id, target_plan, expiry_date_iso)
                           if success:
                               logging.info(f"✅ Base de datos actualizada para user {user_id}. Nuevo plan: {target_plan}, Expira: {expiry_date_iso}")
                           else:
                               logging.error(f"❌ Falló la actualización de la base de datos para user {user_id} (Plan: {target_plan})" )
                        else:
                           logging.error("La función update_user_plan no es callable (¿error de importación?)")
                    except Exception as e:
                        logging.error(f"Excepción al llamar a update_user_plan para user {user_id}: {e}")

            except (ValueError, TypeError) as e:
                logging.error(f"Error procesando client_reference_id '{client_reference_id}' como int: {e}")
            except Exception as e:
                 logging.error(f"Error inesperado procesando sesión {session.get('id')} para user {client_reference_id}: {e}")

        else:
            logging.warning(f"Evento checkout.session.completed recibido pero "
                            f"payment_status no es 'paid' ('{payment_status}') o falta client_reference_id ('{client_reference_id}') "
                            f"o subscription ('{subscription_id}'). No se procesa.")

    # --- Manejar otros eventos si es necesario ---
    # Ejemplo: invoice.payment_succeeded para renovaciones
    # elif event['type'] == 'invoice.payment_succeeded':
    #     invoice = event['data']['object']
    #     # Lógica para manejar renovaciones...
    #     logging.info(f"Procesando invoice.payment_succeeded: {invoice.get('id')}")
    #     pass
    else:
        logging.info(f"Evento no manejado recibido: {event['type']}")

    # Enviar respuesta a Stripe confirmando recepción
    return jsonify({'status': 'received'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080)) # Cambiado default a 8080 por si acaso
    logging.info(f"Iniciando servidor Flask en el puerto {port}")
    app.run(host='0.0.0.0', port=port) 
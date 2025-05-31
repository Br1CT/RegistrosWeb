import logging
import uuid
import os
import json
import azure.functions as func
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        logging.info("🔵 Función guardarLectura iniciada")

        # Determinar el método HTTP de la solicitud
        http_method = req.method.lower()

        if http_method == "post":
            # --- Lógica para POST (guardar datos del ESP8266) ---
            logging.info("Detected POST request.")
            # 1️⃣  Leer JSON del cuerpo de la petición
            try:
                data = req.get_json()
                logging.info(f"📨 Datos recibidos: {data}")
            except ValueError:
                logging.error("❌ JSON inválido – no se pudo deserializar el cuerpo para POST")
                return func.HttpResponse(
                    "Cuerpo inválido – envía un JSON válido",
                    status_code=400
                )

            # 2️⃣  Asegurar campo id (Cosmos DB siempre requiere id)
            # Usar UID + Timestamp para asegurar id único y evitar colisiones si el ESP envía el mismo UID varias veces seguidas
            if "uid" in data and "timestamp" in data:
                # Reemplazar caracteres no permitidos en IDs si uid/timestamp los tienen
                clean_uid = data["uid"].replace("/", "_").replace("\\", "_").replace("#", "_").replace("?", "_")
                clean_timestamp = data["timestamp"].replace(" ", "_").replace(":", "-").replace(".", "_")
                data["id"] = f"{clean_uid}-{clean_timestamp}-{str(uuid.uuid4())[:8]}" # Añadir un pequeño uuid para mayor seguridad
            elif "id" not in data:
                data["id"] = str(uuid.uuid4())
            
            logging.info(f"🔑 id asignado/generado: {data['id']}")


            # 3️⃣  Conexión a Cosmos DB usando variables de entorno
            endpoint = os.environ["COSMOS_ENDPOINT"]
            key = os.environ["COSMOS_KEY"]
            database_name = os.environ["COSMOS_DATABASE"]    # paquetes
            container_name = os.environ["COSMOS_CONTAINER"]  # lecturas

            logging.info("🔐 Credenciales obtenidas. Creando cliente Cosmos…")
            client = CosmosClient(endpoint, key)
            database = client.get_database_client(database_name)
            container = database.get_container_client(container_name)
            logging.info("📦 Conexión a container Cosmos establecida")

            # 4️⃣  Insertar el documento
            container.create_item(body=data)
            logging.info(f"✅ Lectura guardada en Cosmos DB: {data}")

            return func.HttpResponse(
                "Lectura guardada correctamente.",
                status_code=200
            )

        elif http_method == "get":
            # --- Lógica para GET (obtener la última lectura para la página web) ---
            logging.info("Detected GET request. Fetching latest reading from Cosmos DB.")

            # 1️⃣  Conexión a Cosmos DB usando variables de entorno
            endpoint = os.environ["COSMOS_ENDPOINT"]
            key = os.environ["COSMOS_KEY"]
            database_name = os.environ["COSMOS_DATABASE"]    # paquetes
            container_name = os.environ["COSMOS_CONTAINER"]  # lecturas

            logging.info("🔐 Credenciales obtenidas para GET. Creando cliente Cosmos…")
            client = CosmosClient(endpoint, key)
            database = client.get_database_client(database_name)
            container = database.get_container_client(container_name)
            logging.info("📦 Conexión a container Cosmos establecida para GET")

            # 2️⃣  Consultar la última lectura
            # Ordenar por timestamp en forma descendente y tomar el primero.
            # Asegúrate que 'timestamp' sea un campo que se pueda ordenar (string ISO 8601 o datetime).
            # Tu ESP envía "YYYY-MM-DD HH:MM:SS" que es un string. Para una ordenación correcta
            # en Cosmos DB, es mejor usar ISO 8601 extendido (con milisegundos y Z para UTC)
            # o asegurarse de que el formato "YYYY-MM-DD HH:MM:SS" sea consistente y permita la ordenación lexicográfica.
            # El formato actual "YYYY-MM-DD HH:MM:SS" funciona bien para ordenación lexicográfica.
            query = "SELECT TOP 1 * FROM c ORDER BY c.timestamp DESC"
            
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            
            if not items:
                logging.info("No se encontraron lecturas en Cosmos DB.")
                return func.HttpResponse(
                    "No hay lecturas disponibles.",
                    status_code=404
                )
            
            latest_reading = items[0]
            logging.info(f"✅ Última lectura obtenida: {latest_reading}")

            # Devolver el JSON de la última lectura
            return func.HttpResponse(
                json.dumps(latest_reading),
                mimetype="application/json",
                status_code=200
            )

        else:
            # Método HTTP no soportado
            logging.warning(f"⚠️ Método HTTP no soportado: {http_method}")
            return func.HttpResponse(
                "Método HTTP no soportado. Usa POST para guardar o GET para obtener la última lectura.",
                status_code=405 # Method Not Allowed
            )

    except CosmosResourceNotFoundError as cosmos_err:
        logging.error(f"❌ Error de recurso Cosmos DB: {cosmos_err}. Revisa nombres de DB/Contenedor.")
        return func.HttpResponse(
            "Error de configuración de Cosmos DB.",
            status_code=500
        )
    except Exception as e:
        # 5️⃣  Cualquier error imprevisto se registra aquí
        logging.exception(f"🔥 Error inesperado: {e}")
        return func.HttpResponse(
            "Error interno del servidor.",
            status_code=500
        )
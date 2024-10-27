import os
import time
import requests
import influxdb_client
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

### CONSTANTES SERVICIO TERMARIA
BASE_URL = "https://termaria.deporsite.net/ocupacion-aforo"
AJAX_URL = "https://termaria.deporsite.net/ajax/TInnova_v2/Listado_OcupacionAforo/llamadaAjax/obtenerOcupacion"

### LEER VARIABLES DE ENTORNO
try:
    TIEMPO_ESPERA = os.environ['APP_AFORO_TIEMPO_ESPERA']
except KeyError:
    TIEMPO_ESPERA = 120 # por defecto se consulta cada 2 minutos

### CONSTANTES SERVICIO INFLUXDB

try:
    INFLUX_SERVER = os.environ['APP_AFORO_INFLUX_SERVER']
    INFLUX_ORG = os.environ['APP_AFORO_INFLUX_ORG']
    INFLUX_BUCKET = os.environ['APP_AFORO_INFLUX_BUCKET']
    INFLUX_TOKEN = os.environ['APP_AFORO_INFLUX_TOKEN']
except KeyError as e:
    print("ERROR!! Falta alguna variable de entorno de INFLUX: ", str(e))
    exit(-1)

### CONEXION TLS A INFLUX

try:
    if os.environ['APP_AFORO_INFLUX_SSLVERIFY'] in {"True", "true", "yes"}:
        INFLUX_SSLVERIFY = True
    elif os.environ['APP_AFORO_INFLUX_SSLVERIFY'] in {"False", "False", "no"}:
        INFLUX_SSLVERIFY = False
    else:
        print("ERROR!! La variable APP_AFORO_INFLUX_SSLVERIFY tiene un valor erróneo", os.environ['APP_AFORO_INFLUX_SSLVERIFY'])
        exit(-1)
except KeyError:
    INFLUX_SSLVERIFY = True

try:
    INFLUX_SSLCACERT = os.environ['APP_AFORO_INFLUX_SSL_CACERT']
except KeyError:
    INFLUX_SSLCACERT = ""

def get_crsf_token(input: str) -> str:
    # index +32 porque es la longitud del string de búsqueda
    inicio = input.index("<meta name=\"csrf-token\" content=") + 32
    fin = input[inicio:].index("/>")
    token = input[inicio:inicio+fin].replace("\"","").strip()
    return token

# Objeto que almacena las cookies y tokens de sesión
# Resulta util para poder pasarlo con las llamadas y que lo vayan actualizando
# Es inmutable a nivel de propiedades, lo único que permite es actualizar el valor de las cookies de forma controlada
# Cuando la sesión caduca (es decir, el token csrf ya no vale), hay que descartarlo e instanciar uno nuevo
class SessionInfo():
    def __init__(self, cookiejar, csrf_token):
        self._cookiejar = cookiejar
        self._csrf = csrf_token
    
    @property
    def cookiejar(self):
        return self._cookiejar
    
    @property
    def csrf_token(self):
        return self._csrf
    
    def update_cookies(self, new_cookies):
        self._cookiejar.update(new_cookies)

def peticion_inicial() -> SessionInfo:
    # Petición inicial a la URL base para autenticar
    base_req = requests.get(BASE_URL)
    # Controlamos que la respuesta sea OK
    if base_req.status_code == 200:
        # Nos quedamos las cookies
        cookie_jar = base_req.cookies
        # Nos quedamos el token CSRF
        csrf_token = get_crsf_token(base_req.text)
        print("Nuevo token CSRF", csrf_token)
        # Devolvemos un objeto de sesión
        return SessionInfo(cookie_jar, csrf_token)
    else:
        # En caso de error en la petición base, devolvemos nulo y se aborta la aplicación
        print("ERROR: Base Req devuelve status code", base_req.status_code)
        return None

def peticion_aforo(session_info: SessionInfo) -> tuple[int, list]:
    # Hacemos la petición POST a la URL del servicio
    # autenticandonos con los datos que sacamos de la petición inicial
    aforo_req = requests.post(AJAX_URL, headers={"X-Csrf-Token": session_info.csrf_token, "X-Requested-With": "XMLHttpRequest"}, cookies=session_info.cookiejar)

    # Comprobamos el status code de la respuesta
    if aforo_req.status_code == 200:
        # Actualizamos cookies en memoria
        session_info.update_cookies(aforo_req.cookies)
        # Parseamos salida en JSON y devolvemos
        return (aforo_req.status_code, aforo_req.json())
    else:
        # Devolvemos el código de estado erróneo y se trata fuera de esta función
        return (aforo_req.status_code, None)

def parsear_info_aforo(lista_aforos) -> list[influxdb_client.Point]:
    # lista_aforos es una lista de diccionarios, en la que cada diccionario contiene:
    # {'IdRecinto': 1, Id del recinto
    # 'Recinto': 'CIRCUITO TERMAL', Nombre del recinto
    # 'Ocupacion': 0,
    # 'Entradas': 0,
    # 'Salidas': 0,
    # 'Aforo': 0}
    ###
    # Creamos una lista para guardar los datapoints de Influx
    lista_datapoints = list()
    for aforo in lista_aforos:
        # Escribimos ocupacion, entradas, salidas y aforo
        for key in {"Ocupacion", "Entradas", "Salidas", "Aforo"}:
            lista_datapoints.append(
                influxdb_client.Point("aforo")
                .tag("id_recinto", str(aforo['IdRecinto']))
                .tag("nombre_recinto", str(aforo['Recinto']).title())
                .field(key.lower(), aforo[key]))
        # Calculamos y escribimos el porcentaje de ocupación
        if aforo['Aforo'] > 0:
            # Calculamos el porcentaje, redondeando a dos decimales
            ocupacion_pct = round((aforo['Ocupacion']/aforo['Aforo'])*100,2)
        else:
            # Si no tenemos el aforo, no podemos calcular ocupacion, la ponemos a cero
            ocupacion_pct = 0.00
        lista_datapoints.append(
            influxdb_client.Point("aforo")
            .tag("id_recinto", str(aforo['IdRecinto']))
            .tag("nombre_recinto", str(aforo['Recinto']).title())
            .field("ocupacion_pct", ocupacion_pct))
    # Devolvemos la lista de "Points"
    return lista_datapoints

def bucle_principal(session_info: SessionInfo, influx_api_writer: influxdb_client.WriteApi) -> int:
    while (True):
        # En un bucle hacemos la petición de aforo
        statuscode, lista_aforos = peticion_aforo(session_info)
        if statuscode == 200:
            # Si sale bien, parseamos la información y la escribimos
            # usando la API de Influx
            # Al "writer" se le puede pasar un único "Point" o bien
            # un elemento iterable con Points, que es lo que le pasamos aquí
            influx_api_writer.write(
                bucket=INFLUX_BUCKET,
                org=INFLUX_ORG,
                record=parsear_info_aforo(lista_aforos)
                )
        else:
            # Si sale mal, devolvemos el status code y escapamos del bucle
            return statuscode
        # Esperamos antes de repetir
        time.sleep(TIEMPO_ESPERA)

def main():
    print("Iniciando...")
    # Inicializamos el cliente de InfluxDB
    if len(INFLUX_SSLCACERT) == 0:
        cliente_influx = InfluxDBClient(url=INFLUX_SERVER,token=INFLUX_TOKEN,org=INFLUX_ORG,verify_ssl=INFLUX_SSLVERIFY)
    else:
        cliente_influx = InfluxDBClient(url=INFLUX_SERVER,token=INFLUX_TOKEN,org=INFLUX_ORG,verify_ssl=INFLUX_SSLVERIFY,ssl_ca_cert=INFLUX_SSLCACERT)
    influx_api_writer = cliente_influx.write_api(write_options=SYNCHRONOUS)
    while (True):
        # Iniciamos la sesión haciendo la petición inicial
        session_info = peticion_inicial()
        if session_info is None:
            # Salimos del bucle y terminamos ejecución
            break

        # Llamamos al bucle principal y esperamos a que vuelva la función
        # cuando vuelve es porque ha pasado algo
        try:
            status_code = bucle_principal(session_info, influx_api_writer)
        except:
            # Si hay una excepción no controlada en el bucle principal, salimos limpiamente y cerramos el handler de Influx
            print("Saliendo...")
            break

        # Si devuelve un 419 es porque se caducó la sesión y hay que reautenticar
        if status_code == 419:
            print("Status Code 419 Sesión caducada. Reautenticando...")
            # Volvemos a empezar desde el principio
            continue
            # Ya que Python no soporta recursividad de cola, lo implementamos dentro
            # de un bucle while infinito y controlamos el avance del bucle
            #
            # Otra posibilidad aquí sería que no existiera el bucle, y en lugar de
            # "continue", volver a llamar a "main". Funcionalmente es equivalente, pero
            # no se libera el stack de memoria de la llamada anterior, y acabaría
            # crasheando por stack overflow
        else:
            print("ERROR: Status code de la petición AJAX es:", status_code)
            break
    # Siempre que salimos del bucle es porque algo ha ido mal, por lo que devolvemos un código de salida erróneo (negativo)
    influx_api_writer.close()
    cliente_influx.close()
    exit(-1)

if __name__ == "__main__":
    main()

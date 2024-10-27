# ControlAforoTermaria

Esta aplicación Python consulta la API de Deporsite para extraer la información de aforo de Termaria - Casa del Agua de A Coruña, y exporta la información a InfluxDB

## Uso

La aplicación puede utilizarse nativamente o en un contenedor Docker. En ambos casos, se debe tener en cuenta lo siguiente:

#### Variables de entorno

Se utilizan variables de entorno para los parámetros de conexión a la instancia de InfluxDB.

- APP_AFORO_INFLUX_SERVER: La URL de conexión al servicio de InfluxDB
- APP_AFORO_INFLUX_ORG: La organización en InfluxDB
- APP_AFORO_INFLUX_BUCKET: El Bucket donde se almacena la información en InfluxDB
- APP_AFORO_INFLUX_TOKEN: El token de autenticación para escribir en InfluxDB

Adicionalmente, existe una variable APP_AFORO_TIEMPO_ESPERA que se puede utilizar para especificar cada cuanto tiempo se hace la consulta. Si no se define, por defecto el tiempo es de 2 minutos.

#### Certificado SSL

La conexión a InfluxDB es segura y utiliza TLS. Por defecto, se utiliza el almacén de certificados del sistema. Existen dos variables de entorno para controlar el comportamiento:

- APP_AFORO_INFLUX_SSLVERIFY: Indica si se comprueba el certificado. Por defecto es True
- APP_AFORO_INFLUX_SSL_CACERT: Indica la ruta a un certificado de CA, si la CA que utiliza el servidor no está en el almacén de certificados del sistema

### Uso en Docker

En el repositorio se proporciona el Dockerfile, pero no se proporciona una imagen de Docker. El usuario debe construír su propia imagen y almacenarla localmente en su máquina o subirla a un registry de su elección. El comando para construír la imagen es sencillo:

```console
docker build -t aforo-termaria .
```

O si se desea subir a un registry

```console
docker build -t whatever-registry.com/aforo-termaria:latest .
docker push whatever-registry.com/aforo-termaria:latest
```

Para lanzar el contenedor de docker de forma "standalone", se lanzaría con el siguiente comando, incluyendo el fichero con las variables de entorno, y pasando como bind mount el fichero del certificado, en caso de utilizarse.

```console
docker run --env-file aforo_termaria.env -v ./ssl_cacert.crt:/usr/src/app/ssl_cacert.crt --name aforo-termaria-app aforo-termaria
```

Otra opción es utilizar docker compose o docker swarm. Ver la documentación oficial de Docker al respecto

### Uso nativo

Para usar la aplicación nativamente, se debe crear un entorno virtual de Python e instalar los paquetes indicados en el fichero requirements.txt. La aplicación está desarrollada y probada en Python 3.12.7, aunque debería funcionar en cualquier versión posterior a 3.8.

Adicionalmente, el usuario debe crear las variables de entorno y darle los valores adecuados, o modificar el código en el fichero aforo-termaria.py e indicar directamente sus valores de configuración. En el caso de querer utilizar un certificado de CA específico, debe incluírlo e indicar su ruta.

## Esquema de datos en InfluxDB

La aplicación almacena los datos en un único "measurement" llamado "aforo". Los "fields" almacenados son:

- entradas: Número de entradas en sala en el día
- salidas: Número de salidas de la sala en el día
- aforo: Capacidad máxima de la sala. No está establecida en todas las salas
- ocupacion: Número actual de personas en la sala. Es la diferencia entre las entradas y las salidas
- ocupacion_pct: Porcentaje de ocupación, en caso de existir el dato de aforo máximo.

Adicionalmente, cada datapoint se le añaden dos "tags":

- id_recinto: Un identificador numérico que Termaria le da a cada uno de los recintos. A fecha de octubre de 2016, hay 16 recintos registrados
- nombre_recinto: El nombre del recinto al que hace referencia el datapoint, formateado como title case

# Generar la plantilla del forge (DLL .NET decompilable)

El forge (`moqesh/forge.py`) sirve binarios señuelo con credenciales embebidas.
Para que el señuelo sea un **DLL .NET real y decompilable** (dnSpy/ILSpy) sin
exigir el SDK de .NET en runtime, se parte de una **plantilla pre-forjada** que
se genera **una sola vez, offline**, y luego se parchean sus bytes por deployment.

Si la plantilla no está presente, el forge degrada a un binario PE con las
credenciales embebidas en claro (recuperables con `strings`). Todo sigue
funcionando; solo se pierde la decompilación "bonita".

## Requisito

La plantilla DEBE contener estos literales de ancho fijo (el parcheo respeta su
longitud exacta para no desplazar la metadata del PE):

| Campo              | Placeholder (ASCII)                 | Longitud |
|--------------------|-------------------------------------|----------|
| connection_string  | `MQCONN__` + `0` × 120              | 128      |
| internal_api_base  | `MQAPI__` + `0` × 57                | 64       |
| bearer_token       | `MQBEARER__` + `0` × 118            | 128      |

## Pasos (con el SDK de .NET en una máquina de build)

1. Crear un proyecto de librería:

   ```bash
   dotnet new classlib -n PortalTemplate -o portal-template
   ```

2. Reemplazar `Class1.cs` por una clase con los placeholders como constantes:

   ```csharp
   namespace Portal.Internal
   {
       internal static class AppConfig
       {
           public const string ConnectionString =
               "MQCONN__000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";
           public const string InternalApiBase =
               "MQAPI__000000000000000000000000000000000000000000000000000";
           // Token de servicio (en real iría cifrado; aquí como constante para el señuelo).
           public const string ServiceToken =
               "MQBEARER__000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";
       }
   }
   ```

3. Compilar en Release y copiar el DLL a los assets del paquete:

   ```bash
   dotnet build -c Release portal-template
   cp portal-template/bin/Release/*/PortalTemplate.dll moqesh/assets/portal_template.dll
   ```

El forge detecta `moqesh/assets/portal_template.dll` automáticamente. Para usar
otra ruta, pásala al construir `AssemblyForge(template_path=...)`.

> Nota: los placeholders son literales UTF-16 en el heap `#US` del PE; el parcheo
> busca su codificación UTF-16LE y la sustituye por el valor del deployment
> (rellenado con base62 determinista hasta la misma longitud).

# Bitácora — Gestor Diario y Análisis de Ritmo Personal

Aplicación de escritorio local desarrollada en **Python**, **SQLite** y **pywebview** (interfaz web embebida en HTML/CSS/JS) para organizar tareas diarias, registrar bitácoras de energía y estado de ánimo, y detectar patrones de productividad y procrastinación sin depender de servicios en la nube ni suscripciones.

## Por qué este proyecto (y el enfoque sin planes de pago de IA)

Uno de los objetivos de este trabajo es demostrar que **no es necesario pagar suscripciones costosas de IA** para construir herramientas útiles, funcionales y bien estructuradas. Durante el desarrollo se combinaron **Claude (plan gratuito)** y **Gemini (plan gratuito)** de forma iterativa:

- **Diseño funcional y estructura:** definir las tablas (`tareas` y `bitacora`), métricas de cumplimiento y reglas de retroalimentación (`lecturas()`).
- **Iteración por módulos:** construir y depurar por partes (esquema SQLite, bridge `pywebview.api`, interfaz y gráficos/análisis) en lugar de pedir un monolito de una sola vez, cuidando los límites de contexto de los planes gratuitos.
- **Revisión y control humano:** probar cada función en local, verificar consultas SQLite y ajustar el código a mis necesidades reales de organización.

## Características principales

- **Vista Hoy:** gestión de tareas con categorías, prioridad (Alta, Media, Baja), tiempo estimado vs. real, arrastre de pendientes de días anteriores y anillo de progreso diario.
- **Bitácora diaria:** registro rápido de notas junto con escalas de **Energía** (1–5) y **Ánimo** (1–5).
- **Análisis de ritmo:** cálculo de porcentaje de cumplimiento, minutos invertidos, racha de días con ≥80% de avance, relación tiempo real/estimado y lecturas automáticas (por ejemplo, franjas horarias con mayor energía o categorías con menor cumplimiento).
- **Privacidad y persistencia local:** los datos se guardan localmente en `bitacora.db` (configurable mediante la variable de entorno `BITACORA_DB`).

## Instalación y ejecución

```bash
pip install -r requirements.txt
python bitacora_web.py

# Jerarquía de Riesgos y Prioridades

Este documento detalla la prioridad de los mecanismos de protección implementados en el bot para garantizar la seguridad del capital.

## 🥇 Prioridad 1: Kill Switch & Daily Loss (Global)
El **Kill Switch** es la protección suprema y actúa sobre **todos** los símbolos simultáneamente.

- **Activación**: Se dispara si el PnL del día alcanza el límite de pérdida configurado (`DAILY_LOSS_LIMIT`) respecto al equity con el que se inició el día (`day_start_equity`).
- **Comportamiento**: 
  - Cierra todas las posiciones abiertas inmediatamente.
  - Bloquea **totalmente** la apertura de nuevas posiciones o grids para cualquier símbolo.
  - Persiste entre reinicios (vía `risk_state.json`).
- **Desactivación**: Únicamente se resetea al inicio de un nuevo día (UTC 00:00) o mediante intervención manual borrando el estado.

## 🥈 Prioridad 2: Modo Seguro (Safe Mode - Global)
Protección técnica ante inconsistencias de datos o fallos del exchange.

- **Activación**: Si el capital detectado (`equity`) es 0 o negativo.
- **Comportamiento**: Bloquea nuevas entradas. Solo permite el cierre de lo existente.

## 🥉 Prioridad 3: Cooldown por Símbolo (Local)
Protección específica para evitar "overtrading" o capturar el mismo rango de precio repetidamente.

- **Activación**: Después de cerrar una posición o reconstruir un grid.
- **Comportamiento**: Impide que ese símbolo específico opere durante `COOLDOWN_MINUTES`.
- **Interacción**: Si el Kill Switch Global está activo, los símbolos ignoran su cooldown y permanecen bloqueados aunque el tiempo de espera haya expirado.

---
**Resumen de Prioridad**:
`Kill Switch (Global)` > `Safe Mode (Technical)` > `Daily Loss (Global)` > `Cooldown (Symbol)`

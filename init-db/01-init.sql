-- ==============================================================================
-- ESQUEMA DE BASE DE DATOS: SISTEMA DE GESTIÓN DE CITAS Y NOTIFICACIONES
-- ==============================================================================

-- 1. Habilitar extensión para generación de identificadores UUID
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Definición de Tipos ENUM
CREATE TYPE rol_usuario_enum AS ENUM (
    'ADMINISTRADOR',
    'TECNICO',
    'CLIENTE'
);

CREATE TYPE estado_cita_enum AS ENUM (
    'PENDIENTE',      -- Cita recién creada
    'NOTIFICADA',     -- Recordatorio de 24h enviado al cliente
    'CONFIRMADA',     -- Cliente confirmó asistencia
    'CANCELADA',              -- Cancelada por cliente o administrador
    'REQUIERE_REASIGNACION',  -- Técnico rechazó o no disponible, cliente espera reasignación
    'EN_PROGRESO',            -- Técnico inició la atención
    'COMPLETADA'              -- Servicio finalizado
);

CREATE TYPE tipo_notificacion_enum AS ENUM (
    'CREACION',
    'RECORDATORIO_24H',
    'CONFIRMACION',
    'CANCELACION'
);

CREATE TYPE canal_notificacion_enum AS ENUM (
    'WHATSAPP',
    'EMAIL'
);

-- ==============================================================================
-- 3. TABLA: USUARIOS (Administradores, Técnicos y Clientes)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    telefono_whatsapp VARCHAR(30) NOT NULL, -- Formato E.164 ej: +573001234567
    rol rol_usuario_enum NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 4. TABLA: CITAS
-- ==============================================================================
CREATE TABLE IF NOT EXISTS citas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    tecnico_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    admin_id UUID REFERENCES usuarios(id) ON DELETE SET NULL, -- Administrador/organizador responsable de la cita
    titulo VARCHAR(200) NOT NULL,
    descripcion TEXT,
    direccion_servicio TEXT NOT NULL,
    fecha_inicio TIMESTAMPTZ NOT NULL,
    fecha_fin TIMESTAMPTZ NOT NULL,
    estado estado_cita_enum NOT NULL DEFAULT 'PENDIENTE',
    microsoft_event_id VARCHAR(255), -- ID retornado por Microsoft Graph API
    recordatorio_24h_enviado BOOLEAN NOT NULL DEFAULT FALSE,
    recordatorio_enviado_at TIMESTAMPTZ,
    recordatorio_cliente_enviado BOOLEAN NOT NULL DEFAULT FALSE,
    recordatorio_tecnico_enviado BOOLEAN NOT NULL DEFAULT FALSE,
    confirmacion_cliente VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, CONFIRMADA, CANCELADA
    confirmacion_tecnico VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, CONFIRMADA, CANCELADA
    fecha_confirmacion_cliente TIMESTAMPTZ,
    fecha_confirmacion_tecnico TIMESTAMPTZ,
    motivo_cancelacion TEXT,
    fecha_inicio_real TIMESTAMPTZ,
    fecha_fin_real TIMESTAMPTZ,
    calificacion SMALLINT CHECK (calificacion BETWEEN 1 AND 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_rango_fechas CHECK (fecha_fin > fecha_inicio)
);

-- ==============================================================================
-- 5. TABLA: HISTORIAL DE NOTIFICACIONES (Auditoría de mensajes)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS historial_notificaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cita_id UUID REFERENCES citas(id) ON DELETE CASCADE,
    destinatario_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    tipo tipo_notificacion_enum NOT NULL,
    canal canal_notificacion_enum NOT NULL DEFAULT 'WHATSAPP',
    mensaje_id_externo VARCHAR(255), -- ID devuelto por Meta Cloud API (wamid.HBg...)
    estado_envio VARCHAR(50) NOT NULL DEFAULT 'ENVIADO',
    respuesta_recibida TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 6. ÍNDICES DE ALTO RENDIMIENTO
-- ==============================================================================
-- Optimiza la consulta recurrente del Cron (Paso 3) que busca citas para recordatorio
CREATE INDEX IF NOT EXISTS idx_citas_recordatorio_cron 
ON citas (fecha_inicio, estado, recordatorio_24h_enviado);

-- Búsqueda rápida de citas por usuario
CREATE INDEX IF NOT EXISTS idx_citas_cliente ON citas (cliente_id);
CREATE INDEX IF NOT EXISTS idx_citas_tecnico ON citas (tecnico_id);

-- Búsqueda de usuarios por teléfono para mapear respuestas de WhatsApp entrantes
CREATE INDEX IF NOT EXISTS idx_usuarios_telefono ON usuarios (telefono_whatsapp);
CREATE INDEX IF NOT EXISTS idx_usuarios_rol ON usuarios (rol);

-- ==============================================================================
-- 7. FUNCIÓN Y TRIGGERS PARA AUTO-ACTUALIZAR updated_at
-- ==============================================================================
CREATE OR REPLACE FUNCTION actualizar_timestamp_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_usuarios_updated_at ON usuarios;
CREATE TRIGGER trg_usuarios_updated_at
BEFORE UPDATE ON usuarios
FOR EACH ROW
EXECUTE FUNCTION actualizar_timestamp_updated_at();

DROP TRIGGER IF EXISTS trg_citas_updated_at ON citas;
CREATE TRIGGER trg_citas_updated_at
BEFORE UPDATE ON citas
FOR EACH ROW
EXECUTE FUNCTION actualizar_timestamp_updated_at();

-- ==============================================================================
-- 8. DATOS SEMILLA (Seed Data de Prueba)
-- ==============================================================================
INSERT INTO usuarios (id, nombre, email, telefono_whatsapp, rol) VALUES
('a0000000-0000-0000-0000-000000000001', 'Admin Principal', 'admin@empresa.com', '+573001112233', 'ADMINISTRADOR'),
('b0000000-0000-0000-0000-000000000002', 'Carlos Técnico', 'carlos.tecnico@empresa.com', '+573104445566', 'TECNICO'),
('c0000000-0000-0000-0000-000000000003', 'Juan Cliente', 'juan.cliente@gmail.com', '+573207778899', 'CLIENTE')
ON CONFLICT (email) DO NOTHING;

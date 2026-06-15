"""Constants for the Agribuddy integration."""

DOMAIN = "agribuddy"

# ── Config keys ────────────────────────────────────────────────────────────
CONF_DAYSTROM_URL = "daystrom_url"
CONF_DAYSTROM_API_KEY = "daystrom_api_key"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_AI_API_BASE = "ai_api_base"
CONF_AI_API_KEY = "ai_api_key"
CONF_AI_MODEL = "ai_model"

# ── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_UPDATE_INTERVAL = 1440  # minutes (24h)
DEFAULT_NAME = "Agribuddy"

# ── Plant start types ──────────────────────────────────────────────────────
START_TYPE_SEED = "seed"
START_TYPE_TRANSPLANT = "transplant"
START_TYPES = [START_TYPE_SEED, START_TYPE_TRANSPLANT]

# ── Manual event types ─────────────────────────────────────────────────────
EVENT_WATERED = "watered"
EVENT_FERTILIZED = "fertilized"
EVENT_PEST = "pest_spotted"
EVENT_BLIGHT = "blight"
EVENT_SNOW = "snow"
EVENT_HARVESTED = "harvested"
EVENT_TRANSPLANTED = "transplanted"
EVENT_SPROUTED = "sprouted"
EVENT_PLANTED = "planted"
EVENT_DEAD = "dead"
EVENT_OTHER = "other"

MANUAL_EVENT_TYPES = [
    EVENT_WATERED,
    EVENT_FERTILIZED,
    EVENT_PEST,
    EVENT_BLIGHT,
    EVENT_SNOW,
    EVENT_HARVESTED,
    EVENT_TRANSPLANTED,
    EVENT_SPROUTED,
    EVENT_DEAD,
    EVENT_OTHER,
]

# ── Auto event types ───────────────────────────────────────────────────────
EVENT_RAIN_DETECTED = "rain_detected"
EVENT_FROST_ALERT = "frost_alert"

DEFAULT_FROST_THRESHOLD_C = 2.0

# ── Storage ────────────────────────────────────────────────────────────────
STORAGE_VERSION = 3
STORAGE_KEY = f"{DOMAIN}.plants"

# ── Services ───────────────────────────────────────────────────────────────
SERVICE_ADD_PLANT = "add_plant"
SERVICE_REMOVE_PLANT = "remove_plant"
SERVICE_LOG_EVENT = "log_event"
SERVICE_REMOVE_EVENT = "remove_event"
SERVICE_UPDATE_OVERRIDES = "update_plant_overrides"
SERVICE_UPDATE_PLANT = "update_plant"

# Service / attribute names
ATTR_PLANT_ID = "plant_id"
ATTR_PLANT_NAME = "plant_name"
ATTR_SPECIES_ID = "species_id"
ATTR_START_TYPE = "start_type"
ATTR_START_DATE = "start_date"
ATTR_LOCATION = "location"
ATTR_EVENT_ID = "event_id"
ATTR_EVENT_TYPE = "event_type"
ATTR_EVENT_NOTE = "note"
ATTR_EVENT_DATE = "date"

from arq.connections import RedisSettings

from ...core.config import settings
from .functions import extract_features_task, notify_nearby_alert_center_task, shutdown, startup

REDIS_QUEUE_HOST = settings.REDIS_QUEUE_HOST
REDIS_QUEUE_PORT = settings.REDIS_QUEUE_PORT


class WorkerSettings:
    functions = [extract_features_task, notify_nearby_alert_center_task]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_CACHE_URL)
    on_startup = startup
    on_shutdown = shutdown
    handle_signals = False

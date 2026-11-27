import os
from django.core.asgi import get_asgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "configs.settings")
application = get_asgi_application()

from integrations.ai_workers.searching_workers import SEARCH_POOL

SEARCH_POOL.start()

from integrations.ai_workers.construction_manager import CONSTRUCTION_MANAGER

CONSTRUCTION_MANAGER.start()

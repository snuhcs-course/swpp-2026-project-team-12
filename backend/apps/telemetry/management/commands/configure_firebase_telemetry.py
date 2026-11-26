"""Recover public Android client configuration using the existing server ADC."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Fetch google-services.json from the existing Firebase project; optionally register the isolated test app.'

    def add_arguments(self, parser):
        parser.add_argument('--register-test-app', action='store_true')
        parser.add_argument('--output', default=str(settings.BASE_DIR.parent / 'client/app/google-services.json'))

    def handle(self, *args, **options):
        import firebase_admin
        from firebase_admin import project_management
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(options={'httpTimeout':15})
        destination = Path(options['output'])
        if destination.exists():
            current = json.loads(destination.read_text())
            if current.get('project_info', {}).get('project_id') != app.project_id:
                raise CommandError('Existing Android configuration belongs to another Firebase project.')
        configs = [json.loads(item.get_config()) for item in project_management.list_android_apps(app)]
        packages = {client['client_info']['android_client_info']['package_name']
                    for config in configs for client in config.get('client', [])}
        if options['register_test_app'] and 'kr.talkdock.app.memorydemo' not in packages:
            item = project_management.create_android_app('kr.talkdock.app.memorydemo',
                display_name='TalkDock telemetry verification', app=app)
            configs.append(json.loads(item.get_config()))
        production = next((config for config in configs if any(
            client['client_info']['android_client_info']['package_name'] == 'kr.talkdock.app'
            for client in config.get('client', []))), None)
        if production is None:
            raise CommandError('Register the production package kr.talkdock.app in this Firebase project first.')
        allowed = {'kr.talkdock.app', 'kr.talkdock.app.memorydemo'}
        clients = {client['client_info']['mobilesdk_app_id']:client
                   for config in configs for client in config.get('client', [])
                   if client['client_info']['android_client_info']['package_name'] in allowed}
        production['client'] = list(clients.values())
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(production, indent=2)+'\n')
        temporary.replace(destination)
        self.stdout.write('Android Firebase configuration saved. Keep google-services.json out of Git.')

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class FirebaseSetupTests(SimpleTestCase):
    def test_fetch_is_read_only_and_registration_is_explicit(self):
        def config(package, app_id):
            return json.dumps({'project_info': {'project_id':'test-project'}, 'client':[
                {'client_info': {'mobilesdk_app_id':app_id,'android_client_info':{'package_name':package}}}]})
        production=SimpleNamespace(get_config=lambda:config('kr.talkdock.app','production'))
        demo=SimpleNamespace(get_config=lambda:config('kr.talkdock.app.memorydemo','test'))
        with tempfile.TemporaryDirectory() as directory, \
             patch('firebase_admin.get_app',return_value=SimpleNamespace(project_id='test-project')), \
             patch('firebase_admin.project_management.list_android_apps',return_value=[production]), \
             patch('firebase_admin.project_management.create_android_app',return_value=demo) as create:
            path=Path(directory)/'google-services.json'
            call_command('configure_firebase_telemetry',output=str(path),stdout=io.StringIO())
            create.assert_not_called()
            call_command('configure_firebase_telemetry',register_test_app=True,output=str(path),stdout=io.StringIO())
            self.assertEqual(len(json.loads(path.read_text())['client']),2)
            create.assert_called_once()
            path.write_text('{"project_info":{"project_id":"another-project"}}')
            with self.assertRaises(CommandError):
                call_command('configure_firebase_telemetry',output=str(path))

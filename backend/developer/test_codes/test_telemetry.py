import io
import json
import logging
import uuid
from unittest.mock import patch
from django.test import TestCase, Client
from integrations.telemetry import JsonFormatter, bind, context, emit, stage
from apps.telemetry.jobs import enqueue, processing
from apps.telemetry.models import WorkItem


class TelemetryTests(TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(JsonFormatter())
        self.logger = logging.getLogger("talkdock.telemetry")
        self.logger.addHandler(self.handler)
        self.addCleanup(self.logger.removeHandler, self.handler)

    def records(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    def test_request_ids_timing_and_no_sensitive_data(self):
        op, req = str(uuid.uuid4()), uuid.uuid4().hex
        response = Client().get('/api/test_reply/?token=PRIVATE', HTTP_X_OPERATION_ID=op,
                                HTTP_X_REQUEST_ID=req, HTTP_AUTHORIZATION='Bearer PRIVATE')
        self.assertEqual(response['X-Request-ID'], req)
        row = self.records()[-1]
        self.assertEqual(row['operation_id'], op)
        self.assertEqual(row['route'], 'api/test_reply/')
        self.assertEqual(row['http_status'], 200)
        self.assertGreaterEqual(row['duration_ms'], 0)
        self.assertNotIn('PRIVATE', self.output.getvalue())
        self.assertEqual(context.get(), {})

    def test_unmatched_path_and_invalid_id_not_logged(self):
        response = Client().get('/PRIVATE/', HTTP_X_OPERATION_ID='PRIVATE', HTTP_X_REQUEST_ID='PRIVATE')
        uuid.UUID(response['X-Operation-ID'])
        self.assertEqual(self.records()[-1]['route'], 'unmatched')
        self.assertNotIn('PRIVATE', self.output.getvalue())

    def test_failed_stage_has_frames_without_exception_message(self):
        with self.assertRaises(ValueError):
            with stage('stt'):
                raise ValueError('PRIVATE transcript')
        row = self.records()[-1]
        self.assertEqual(row['result'], 'error')
        self.assertEqual(row['error_type'], 'ValueError')
        self.assertNotIn('PRIVATE', self.output.getvalue())
        record = logging.LogRecord('provider', logging.ERROR, __file__, 1, 'PRIVATE', (), None)
        self.assertNotIn('PRIVATE', JsonFormatter().format(record))
        self.assertEqual(json.loads(JsonFormatter().format(record))['event_id'],
                         json.loads(JsonFormatter().format(record))['event_id'])

    def test_durable_context_and_retry_identity(self):
        op, req = str(uuid.uuid4()), uuid.uuid4().hex
        with bind(operation_id=op, request_id=req):
            job = enqueue('construction', 'post:1')
        with self.assertRaises(TimeoutError):
            with processing(job):
                raise TimeoutError('PRIVATE')
        self.assertEqual(enqueue('construction', 'post:1').pk, job.pk)
        with processing(job):
            self.assertEqual(context.get()['operation_id'], op)
        job.refresh_from_db()
        self.assertEqual(job.attempts, 2)
        self.assertEqual(job.status, 'success')
        self.assertIsNotNone(job.completed_at)
        self.assertEqual(context.get(), {})

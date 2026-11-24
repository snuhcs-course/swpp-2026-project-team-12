import json
from django.test import TestCase
from apps.accounts.models import User


class AccountFeedbackTests(TestCase):
    def register(self, password, **changes):
        data = dict(username="family_reader", name="정순", gender="female", password=password)
        data.update(changes)
        return self.client.post('/api/accounts/register/', json.dumps(data), content_type='application/json')

    def test_only_failed_password_rules_are_returned_with_field(self):
        cases = [
            ('x7!', '10자 이상', ['숫자를 한 개', '숫자만으로', '너무 흔한']),
            ('Qwerty!LemonTree', '숫자를 한 개', ['10자 이상', '숫자만으로']),
            ('739184650283', '숫자만으로', ['10자 이상', '숫자를 한 개']),
            ('password123', '너무 흔한', ['10자 이상', '숫자를 한 개']),
            ('family_reader9', '계정 정보와 너무 비슷', ['10자 이상', '숫자만으로']),
        ]
        for password, expected, absent in cases:
            with self.subTest(expected=expected):
                response = self.register(password)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['field'], 'password')
                self.assertIn(expected, response.json()['error'])
                for text in absent:
                    self.assertNotIn(text, response.json()['error'])
        self.assertFalse(User.objects.exists())

    def test_password_change_returns_specific_field_without_rotating_session(self):
        account = self.register('Cedar-lake-732!').json()
        response = self.client.patch('/api/accounts/me/', json.dumps({
            'current_password': 'Cedar-lake-732!', 'new_password': '739184650283',
        }), content_type='application/json', HTTP_AUTHORIZATION=f"Bearer {account['token']}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['field'], 'new_password')
        self.assertIn('숫자만으로', response.json()['error'])
        self.assertTrue(User.objects.get().check_password('Cedar-lake-732!'))

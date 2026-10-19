import json
from datetime import time

from django.test import TestCase

from apps.accounts.models import AccessToken, User
from apps.families.models import Membership
from apps.families.services import create_room
from apps.posts.models import Post


class ReviewRoomRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='review_member', display_name='검증 사용자', password='Local-Review-12345')
        other = User.objects.create_user(username='review_other', display_name='다른 가족', password='Local-Review-67890')
        self.a = create_room(self.user, '검증 가족 A', 'Room-12345', time(21))
        self.b = create_room(other, '검증 가족 B', 'Room-67890', time(21))
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer ' + AccessToken.issue(self.user)}

    def post_json(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json', **self.headers)

    def test_existing_member_cannot_create_another_room(self):
        response = self.post_json('/api/families/create/', {'room_name':'새 가족 B', 'password':'New-Room-12345'})
        self.assertEqual(response.status_code, 409, 'Additional room creation must be rejected')
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)

    def test_existing_member_cannot_join_another_room(self):
        response = self.post_json('/api/families/join/', {'invite_code':self.b.invite_code, 'password':'Room-67890', 'slot':'son'})
        self.assertEqual(response.status_code, 409, 'Additional room joining must be rejected')
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)

    def test_created_room_and_actual_post_destination_agree(self):
        created = self.post_json('/api/families/create/', {'room_name':'생성 응답 가족 C', 'password':'New-Room-12345'})
        returned = self.a.pk if created.status_code == 409 else created.json()['room']['id']
        current = self.client.get('/api/families/current/', **self.headers).json()['id']
        upload = self.client.post('/api/posts/', {'caption':'별도 테스트 DB의 검증 소식'}, **self.headers)
        self.assertEqual(upload.status_code, 200)
        destination = Post.objects.get(pk=upload.json()['id']).room_id
        print(f'REVIEW_ROOM_IDS returned={returned} current={current} post_destination={destination}')
        self.assertEqual(returned, destination, 'The displayed create response must match the actual post destination')

    def test_legacy_multiple_memberships_keep_current_room_and_upload_in_sync(self):
        Membership.objects.create(room=self.b, user=self.user, slot='son')
        current = self.client.get('/api/families/current/', **self.headers).json()['id']
        self.assertEqual(current, self.a.pk)
        uploaded = self.client.post('/api/posts/', {'caption':'기존 다중 가입자 검증'}, **self.headers)
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(Post.objects.get(pk=uploaded.json()['id']).room_id, current)
        denied = self.post_json('/api/families/create/', {'room_name':'추가 가족방', 'password':'Room-12345'})
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 2)

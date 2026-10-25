import json
from datetime import time

from django.test import TestCase

from apps.accounts.models import AccessToken, User
from apps.families.models import Membership
from apps.families.services import create_room
from apps.posts.models import Post

from .family_fixtures import add_member


class MultiRoomTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='multi_member', display_name='검증 사용자', password='Local-Review-12345')
        self.other = User.objects.create_user(username='multi_other', display_name='다른 가족', password='Local-Review-67890')
        self.a = create_room(self.user, '검증 가족 A', 'Room-12345', time(21))
        self.b = create_room(self.other, '검증 가족 B', 'Room-67890', time(21))
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer ' + AccessToken.issue(self.user)}

    def post_json(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json', **self.headers)

    def in_room(self, room):
        return {**self.headers, 'HTTP_X_FAMILY_ROOM': str(room if isinstance(room, str) else room.pk)}

    def join_b(self):
        return self.post_json('/api/families/join/', {
            'invite_code': self.b.invite_code, 'password': 'Room-67890',
            'tree_version': 0, 'person_id': 'new_child',
            'additions': [{'id': 'new_child', 'anchor_id': str(self.b.people.get().pk), 'relation': 'child'}],
        })

    def test_member_can_create_another_room(self):
        response = self.post_json('/api/families/create/', {'room_name': '새 가족 C', 'password': 'New-Room-12345'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 2)
        self.assertEqual(response.json()['room']['name'], '새 가족 C')

    def test_member_can_join_another_room_once(self):
        self.assertEqual(self.join_b().status_code, 200)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 2)
        self.b.refresh_from_db()
        owner_person = self.b.members.get(user=self.other).person_id
        again = self.post_json('/api/families/join/', {
            'invite_code': self.b.invite_code, 'password': 'Room-67890', 'tree_version': self.b.tree_version,
            'person_id': 'new_second', 'additions': [{'id': 'new_second', 'anchor_id': str(owner_person), 'relation': 'child'}],
        })
        self.assertEqual(again.status_code, 409)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 2)
        self.assertEqual(self.b.people.count(), 2)

    def test_rooms_lists_memberships_in_join_order(self):
        self.join_b()
        response = self.client.get('/api/families/', **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rooms'], [
            {'id': self.a.pk, 'name': '검증 가족 A', 'is_owner': True, 'member_count': 1},
            {'id': self.b.pk, 'name': '검증 가족 B', 'is_owner': False, 'member_count': 2},
        ])

    def test_header_selects_room_for_current_upload_and_feed(self):
        self.join_b()
        self.assertEqual(self.client.get('/api/families/current/', **self.in_room(self.b)).json()['id'], self.b.pk)
        uploaded = self.client.post('/api/posts/', {'caption': 'B 방 소식'}, **self.in_room(self.b))
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(Post.objects.get(pk=uploaded.json()['id']).room_id, self.b.pk)
        feed_a = self.client.get('/api/posts/', **self.in_room(self.a)).json()['posts']
        feed_b = self.client.get('/api/posts/', **self.in_room(self.b)).json()['posts']
        self.assertEqual([post['id'] for post in feed_a], [])
        self.assertEqual([post['id'] for post in feed_b], [uploaded.json()['id']])

    def test_header_for_other_or_malformed_room_is_rejected(self):
        for value in (self.b.pk, '', 'abc', '-1', '0', '٣', '9' * 30):
            with self.subTest(value=value):
                for path in ('/api/families/current/', '/api/posts/', '/api/digests/history/'):
                    self.assertEqual(self.client.get(path, **self.in_room(str(value))).status_code, 403)
        denied = self.client.post('/api/posts/', {'caption': '남의 방'}, **self.in_room(self.b))
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(Post.objects.filter(room=self.b).exists())

    def test_room_scoped_requests_require_the_header(self):
        add_member(self.b, self.user, -1)
        for path in ('/api/families/current/', '/api/posts/', '/api/digests/history/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, **self.headers).status_code, 403)
        denied = self.client.post('/api/posts/', {'caption': '헤더 없는 소식'}, **self.headers)
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(Post.objects.exists())

    def test_post_access_follows_post_room_membership(self):
        post_b = Post.objects.create(room=self.b, author=self.other, caption='B 방 소식')
        self.assertEqual(self.client.get(f'/api/posts/{post_b.pk}/', **self.headers).status_code, 404)
        add_member(self.b, self.user, -1)
        self.assertEqual(self.client.get(f'/api/posts/{post_b.pk}/', **self.headers).status_code, 200)
        self.assertEqual(self.client.get(f'/api/posts/{post_b.pk}/', **self.in_room(self.a)).status_code, 200)
        comment = self.post_json(f'/api/posts/{post_b.pk}/comments/', {'text': '반가워요'})
        self.assertEqual(comment.status_code, 200)

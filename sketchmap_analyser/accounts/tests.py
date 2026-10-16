from django.contrib.auth import get_user_model
from django.test import TestCase


class AccountCompatibilityTests(TestCase):
    def test_signup_login_and_logout(self):
        response = self.client.post('/accounts/signup/', {
            'username': 'migration-check',
            'password1': 'MapCompatibility_312!',
            'password2': 'MapCompatibility_312!',
        })
        self.assertRedirects(response, '/useraccount/login/')
        user = get_user_model().objects.get(username='migration-check')
        self.assertTrue(user.check_password('MapCompatibility_312!'))
        response = self.client.post('/useraccount/login/', {
            'username': user.username, 'password': 'MapCompatibility_312!',
        })
        self.assertRedirects(response, '/')
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        self.assertRedirects(self.client.post('/useraccount/logout/'), '/')
        self.assertNotIn('_auth_user_id', self.client.session)

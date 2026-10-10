from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from .models import SiteVisit


class ControlCenterTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff_control', password='test12345', is_staff=True)
        self.normal = User.objects.create_user('normal_control', password='test12345')

    def test_only_staff_can_open_panel(self):
        self.client.force_login(self.normal)
        self.assertEqual(self.client.get(reverse('control_dashboard')).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('control_dashboard')).status_code, 200)

    def test_middleware_records_visit(self):
        self.client.get('/login/')
        self.assertTrue(SiteVisit.objects.filter(path='/login/').exists())

    def test_user_actions_are_post_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('control_toggle_user', args=[self.normal.id])).status_code, 405)
        self.client.post(reverse('control_toggle_user', args=[self.normal.id]))
        self.normal.refresh_from_db()
        self.assertFalse(self.normal.is_active)

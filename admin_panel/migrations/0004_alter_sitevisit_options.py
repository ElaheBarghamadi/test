from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('admin_panel', '0003_sitevisit')]
    operations = [
        migrations.AlterModelOptions(
            name='sitevisit',
            options={
                'ordering': ['-created_at'],
                'permissions': [
                    ('access_control_center', 'دسترسی به مرکز کنترل و گزارش‌ها'),
                    ('manage_control_users', 'مدیریت کاربران از مرکز کنترل'),
                ],
                'verbose_name': 'بازدید سایت',
                'verbose_name_plural': 'بازدیدهای سایت',
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('exams', '0014_exam_exam_duration_in_range_and_more')]

    operations = [
        migrations.AddField(
            model_name='exam',
            name='question_policy',
            field=models.CharField(
                choices=[('mixed', 'آزاد — همهٔ انواع سوال'),
                         ('four_choice', 'آزمون تستی استاندارد — فقط چهارگزینه‌ای')],
                default='mixed', max_length=20, verbose_name='قالب سوال‌های آزمون'),
        ),
    ]

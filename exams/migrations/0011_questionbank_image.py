from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0010_bankfolder_questionbank_folder'),
    ]

    operations = [
        migrations.AddField(
            model_name='questionbank',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='question_images/'),
        ),
    ]

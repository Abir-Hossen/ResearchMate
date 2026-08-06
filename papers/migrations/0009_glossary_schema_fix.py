from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0008_papersection_conclusion'),
    ]

    operations = [
        migrations.AddField(
            model_name='glossary',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='glossary',
            name='explanation',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='glossary',
            name='paper_role',
            field=models.TextField(blank=True),
        ),
    ]

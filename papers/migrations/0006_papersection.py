from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0005_aianalysis_analysis_error_aianalysis_raw_response'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaperSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('section_order', models.PositiveIntegerField(default=0)),
                ('summary', models.TextField(blank=True)),
                ('purpose', models.TextField(blank=True)),
                ('key_points', models.JSONField(blank=True, default=list)),
                ('important_terms', models.JSONField(blank=True, default=list)),
                ('student_note', models.TextField(blank=True)),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_learning_sections', to='papers.paper')),
            ],
            options={
                'ordering': ['section_order', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='papersection',
            index=models.Index(fields=['paper', 'section_order'], name='papers_paperse_paper_id_ef9774_idx'),
        ),
    ]

# Generated by Django 5.1.7 on 2025-03-27 15:58

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scores', '0008_alter_game_opponent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='opponent',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='games', to='scores.opponent'),
        ),
    ]

# Generated migration for arrival confirmation fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0041_payment_buyer_tracking_acknowledged_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='buyer_confirmed_arrival',
            field=models.BooleanField(default=False, help_text='Buyer confirmed they arrived at meetup location'),
        ),
        migrations.AddField(
            model_name='transaction',
            name='seller_confirmed_arrival',
            field=models.BooleanField(default=False, help_text='Seller confirmed they arrived at meetup location'),
        ),
        migrations.AddField(
            model_name='transaction',
            name='buyer_arrival_confirmed_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp when buyer confirmed arrival', null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='seller_arrival_confirmed_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp when seller confirmed arrival', null=True),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='buyer_confirmed_meeting',
            field=models.BooleanField(default=False, help_text='Buyer confirmed they will attend meeting'),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='seller_confirmed_meeting',
            field=models.BooleanField(default=False, help_text='Seller confirmed they will attend meeting'),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='buyer_completed',
            field=models.BooleanField(default=False, help_text='Buyer confirmed exchange happened after payment'),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='seller_completed',
            field=models.BooleanField(default=False, help_text='Seller confirmed exchange happened after payment'),
        ),
    ]

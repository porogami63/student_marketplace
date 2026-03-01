# Generated migration to add school logos and new schools

from django.db import migrations

def add_school_logos_and_new_schools(apps, schema_editor):
    School = apps.get_model('marketplace', 'School')
    
    # School logos and data (using common public URLs for university logos)
    schools_data = [
        # Existing "University Belt" schools with logos
        {
            'name': 'University of Santo Tomas',
            'short_name': 'UST',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/b/bf/University_of_Santo_Tomas_seal.png',
            'primary_color': '#8B0000',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'Far Eastern University',
            'short_name': 'FEU',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/4/4a/FEU_seal.png',
            'primary_color': '#003DA5',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'University of the East',
            'short_name': 'UE',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/a/a8/UE_seal.png',
            'primary_color': '#002868',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'National University',
            'short_name': 'NU',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/a/ac/NU_seal.png',
            'primary_color': '#D4A017',
            'secondary_color': '#003366',
        },
        # New Manila schools
        {
            'name': 'Mapua University',
            'short_name': 'Mapua',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/e/e5/Mapuua_University_logo.png',
            'primary_color': '#003DA5',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'Adamson University',
            'short_name': 'Adamson',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/f/f7/Adamson_University_seal_%28old%29.png',
            'primary_color': '#1B4695',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'Polytechnic University of the Philippines',
            'short_name': 'PUP',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/0/0e/PUP_seal_2015.png',
            'primary_color': '#FFD700',
            'secondary_color': '#003DA5',
        },
        {
            'name': 'De La Salle University',
            'short_name': 'DLSU',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/9/97/DLSU_seal_1.svg',
            'primary_color': '#1B3B6F',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'University of the Philippines Manila',
            'short_name': 'UP Manila',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/2/29/UP_Manila_Logo2.png',
            'primary_color': '#003366',
            'secondary_color': '#FFD700',
        },
        {
            'name': 'Ateneo de Manila University',
            'short_name': 'Ateneo',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/a/ab/Ateneo_de_Manila_University_logo.png',
            'primary_color': '#0066CC',
            'secondary_color': '#FFFFFF',
        },
        {
            'name': 'University of the Philippines Diliman',
            'short_name': 'UP Diliman',
            'logo_url': 'https://upload.wikimedia.org/wikipedia/en/3/35/UP_seal_1.png',
            'primary_color': '#003366',
            'secondary_color': '#FFD700',
        },
    ]
    
    for school_data in schools_data:
        School.objects.update_or_create(
            short_name=school_data['short_name'],
            defaults={
                'name': school_data['name'],
                'logo_url': school_data['logo_url'],
                'primary_color': school_data['primary_color'],
                'secondary_color': school_data['secondary_color'],
            }
        )

def reverse_school_logos(apps, schema_editor):
    # This is a safe reverse - just remove the logo URLs
    School = apps.get_model('marketplace', 'School')
    School.objects.all().update(logo_url='')

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0012_remove_profile_average_rating_and_more'),
    ]

    operations = [
        migrations.RunPython(add_school_logos_and_new_schools, reverse_school_logos),
    ]

# Generated migration to update schools with local logo paths

from django.db import migrations

def add_school_logos(apps, schema_editor):
    """Add logo paths to schools matching provided logo files."""
    School = apps.get_model('marketplace', 'School')
    
    # Mapping of school short names to logo filenames
    logo_mapping = {
        'Adamson': 'Adamson.png',
        'Arellano': 'arellano.png',
        'Ateneo': 'ateneo.png',
        'CEU Manila': 'CEU.png',
        'DLSU': 'DLSU.png',
        'FEU': 'FEU.png',
        'LCCM': 'LCCM.png',
        'Letran': 'LETRAN.png',
        'Mapua': 'MAPUA.png',
        'NTC Manila': 'NTC.png',
        'NU': 'NU.png',
        'PLM': 'PLM.png',
        'PNU': 'pnu.png',
        'PUP': 'PUP.png',
        'San Beda': 'SAN BEDA.png',
        'TIP Manila': 'TIP BEST SCHOOL.png',
        'UDM': 'UDM.png',
        'UE': 'UE.png',
        'UP Diliman': 'UP DILIMAN.png',
        'UP Manila': 'UP MANILA.png',
        'UST': 'UST.png',
    }
    
    for short_name, logo_file in logo_mapping.items():
        try:
            school = School.objects.get(short_name=short_name)
            # Use local media path for logos
            school.logo_url = f'/media/UNIV LOGOS/{logo_file}'
            school.save(update_fields=['logo_url'])
            print(f'Updated {short_name} with logo: {logo_file}')
        except School.DoesNotExist:
            print(f'School {short_name} not found in database')

def reverse_logos(apps, schema_editor):
    """Remove logo URLs on reverse."""
    School = apps.get_model('marketplace', 'School')
    School.objects.all().update(logo_url='')

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0016_profile_header_image'),
    ]

    operations = [
        migrations.RunPython(add_school_logos, reverse_logos),
    ]

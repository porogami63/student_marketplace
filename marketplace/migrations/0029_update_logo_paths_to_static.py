# Generated migration to update logo paths from media to static

from django.db import migrations

def update_logo_paths(apps, schema_editor):
    """Update existing school logo paths from media to static."""
    School = apps.get_model('marketplace', 'School')
    
    # Update all schools with the old media path to the new static path
    updated_count = 0
    for school in School.objects.all():
        if school.logo_url and '/media/UNIV LOGOS/' in school.logo_url:
            # Extract just the filename
            filename = school.logo_url.split('/')[-1]
            # Update to static path
            school.logo_url = f'/static/images/university-logos/{filename}'
            school.save(update_fields=['logo_url'])
            updated_count += 1
    
    if updated_count > 0:
        print(f'Updated {updated_count} schools with new logo paths')

def reverse_update(apps, schema_editor):
    """Reverse the logo path update."""
    School = apps.get_model('marketplace', 'School')
    
    updated_count = 0
    for school in School.objects.all():
        if school.logo_url and '/static/images/university-logos/' in school.logo_url:
            # Extract just the filename
            filename = school.logo_url.split('/')[-1]
            # Revert to media path
            school.logo_url = f'/media/UNIV LOGOS/{filename}'
            school.save(update_fields=['logo_url'])
            updated_count += 1
    
    if updated_count > 0:
        print(f'Reverted {updated_count} schools to old logo paths')

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0028_notification_notification_type_and_more'),
    ]

    operations = [
        migrations.RunPython(update_logo_paths, reverse_update),
    ]
